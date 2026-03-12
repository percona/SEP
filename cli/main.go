// Package main implements the SEP Installer as a standalone native Go CLI.
package main

import (
	"bufio"
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"embed"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// =============================================================================
// EMBEDDED RESOURCES
// =============================================================================

//go:embed templates/*
var templateFS embed.FS

// ANSI Color Codes
const (
	Reset   = "\033[0m"
	Red     = "\033[31m"
	Green   = "\033[32m"
	Yellow  = "\033[33m"
	Magenta = "\033[35m"
	Cyan    = "\033[36m"
	Bold    = "\033[1m"
)

type Config struct {
	InstallDir        string
	HttpPort          string
	HttpsPort         string
	Plugins           string
	CreatePMM         bool
	UseExistentPMM    bool
	PmmUser           string
	PmmPass           string
	PmmToken          string
	Engine            string
	DockerToken       string
	Autostart         bool
	Overwrite         bool
	NoInteraction     bool
	ImageName         string
	ImageTag          string
	PmmPublicHost     string
	PmmPort           string
	PmmFrontend       string
	ContainerRegistry string
}

var config Config

func main() {
	initConfig()
	parseArgs()

	printBanner()

	checkPrereqs()
	checkInstallDirWritable()

	if !config.NoInteraction {
		runInteractiveWizard()
		runSummaryScreen()
	} else if !config.CreatePMM {
		if config.PmmUser == "" {
			config.PmmUser = "admin"
		}
		if config.PmmPass == "" {
			config.PmmPass = "admin"
		}
	}

	checkInstallDirWritable()
	handleExistingDirectory()

	fmt.Println("\n" + Bold + Cyan + "Starting Installation..." + Reset)

	tempDir, err := os.MkdirTemp("", "sep-install-*")
	if err != nil {
		logFatalf("Failed to create temporary directory: %v", err)
	}
	defer os.RemoveAll(tempDir)

	secrets := generateSecrets()
	generateTLS(tempDir, "all-in-one", secrets)
	renderTemplates(tempDir, secrets)
	commitFiles(tempDir)
	pullAndStart()
}

func initConfig() {
	home, _ := os.UserHomeDir()
	config = Config{
		InstallDir:        filepath.Join(home, "sep"),
		HttpPort:          getEnvOrDefault("SEP_HTTP_PORT", "8080"),
		HttpsPort:         getEnvOrDefault("SEP_HTTPS_PORT", "8444"),
		Plugins:           getEnvOrDefault("SEP_ENABLED_PLUGINS", "schema_change,archive,backups,checksums,snippets"),
		CreatePMM:         false,
		Engine:            getEnvOrDefault("CONTAINER_ENGINE", "docker"),
		ImageName:         getEnvOrDefault("SEP_IMAGE_NAME", "docker.io/percona/percona-sep"),
		ImageTag:          getEnvOrDefault("SEP_IMAGE_TAG", "latest"),
		PmmPublicHost:     getEnvOrDefault("SEP_PMM_PUBLIC_HOST", "127.0.0.1"),
		PmmPort:           getEnvOrDefault("SEP_PMM_PORT", "8443"),
		ContainerRegistry: getEnvOrDefault("CONTAINER_REGISTRY", "docker.io"),
	}
	config.PmmFrontend = getEnvOrDefault("SEP_PMM_FRONTEND", "https://"+config.PmmPublicHost)
}

func parseArgs() {
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--install-dir":
			config.InstallDir = getArg(args, &i)
		case "--http-port":
			config.HttpPort = getArg(args, &i)
		case "--https-port":
			config.HttpsPort = getArg(args, &i)
		case "--plugins":
			config.Plugins = getArg(args, &i)
		case "--create-pmm-container":
			config.CreatePMM = true
		case "--use-existent-pmm":
			config.CreatePMM = false
			config.UseExistentPMM = true
		case "--pmm-user":
			config.PmmUser = getArg(args, &i)
		case "--pmm-pass":
			config.PmmPass = getArg(args, &i)
		case "--pmm-token":
			config.PmmToken = getArg(args, &i)
		case "--engine":
			config.Engine = getArg(args, &i)
		case "--docker-token":
			config.DockerToken = getArg(args, &i)
		case "--autostart":
			config.Autostart = true
		case "--overwrite":
			config.Overwrite = true
		case "--no-interaction", "--headless", "-y", "--yes":
			config.NoInteraction = true
		case "--help", "-h":
			printUsage()
			os.Exit(0)
		default:
			logFatalf("Unknown option: %s", args[i])
		}
	}
}

func getArg(args []string, i *int) string {
	if *i+1 >= len(args) {
		logFatalf("Missing value for argument: %s", args[*i])
	}
	*i++
	return args[*i]
}

func printBanner() {
	fmt.Print("\033[H\033[2J") // Clear screen
	banner := `
================================================================================
                                SEP INSTALLER
================================================================================
`
	fmt.Println(Bold + Magenta + banner + Reset)
}

func printUsage() {
	fmt.Println(`SEP Installer

USAGE
  ./sep_installer [OPTIONS]

OPTIONS
  --install-dir DIR        Set installation directory (Default: ~/sep)
  --http-port PORT         Set HTTP port (Default: 8080)
  --https-port PORT        Set HTTPS port (Default: 8444)
  --plugins LIST           Comma-separated list of plugins (internal names)
                           Available: schema_change, archive, backups, checksums, snippets, task_manager, mongodb_backups
                           Default: schema_change,archive,backups,checksums,snippets
  --create-pmm-container   Create PMM container as part of the stack (Default: No)
  --use-existent-pmm       Use an external/existing PMM instance (removes PMM from stack)
  --pmm-user USER          PMM Username (for PMM 3 Nomad auth)
  --pmm-pass PASS          PMM Password (for PMM 3 Nomad auth)
  --pmm-token TOKEN        PMM Service Account Token (for PMM Inventory Sync)
  --engine ENGINE          Container engine: docker or podman (Default: docker)
  --docker-token TOKEN     Token for registry login if needed
  --autostart              Start the stack automatically after install
  --overwrite              Overwrite existing installation directory without prompting
  --no-interaction         Skip interactive wizard and use defaults/flags
  --help, -h               Show this help message`)
}

func checkPrereqs() {
	fmt.Printf("[%sINFO%s] Checking system requirements...\n", Cyan, Reset)
	if _, err := exec.LookPath(config.Engine); err != nil {
		logFatalf("Missing required tool: %s", config.Engine)
	}

	err := runCmdWithSpinner(fmt.Sprintf("Checking %s info", config.Engine), config.Engine, "info")
	if err != nil {
		logFatalf("Container engine check failed. Is %s running?", config.Engine)
	}
	fmt.Printf("[%s✓%s] All prerequisites met. Using engine: %s\n", Green, Reset, config.Engine)
}

func checkInstallDirWritable() {
	target := config.InstallDir
	if _, err := os.Stat(target); !os.IsNotExist(err) {
		if err := isWritable(target); err != nil {
			logFatalf("Installation directory '%s' is not writable.", target)
		}
		return
	}

	parentDir := filepath.Dir(target)
	if err := isWritable(parentDir); err != nil {
		logFatalf("Parent directory '%s' is not writable or doesn't exist.", parentDir)
	}
}

func handleExistingDirectory() {
	if !config.Overwrite && !config.NoInteraction {
		if empty, _ := isEmptyDir(config.InstallDir); !empty {
			fmt.Printf("\n[%sWARN%s] Installation directory '%s' already exists and is not empty.\n", Yellow, Reset, config.InstallDir)
			ans := prompt("Proceed anyway? (Existing files may be overwritten) [y/N]", "N")
			if strings.ToLower(ans) != "y" {
				fmt.Println("Installation aborted by user.")
				os.Exit(0)
			}
		}
	}
}

func runInteractiveWizard() {
	fmt.Println("\n--- Configuration Wizard ---")
	config.InstallDir = prompt(fmt.Sprintf("Install Directory [%s]", config.InstallDir), config.InstallDir)

	fmt.Println("\nAvailable Plugins: schema_change, archive, backups, checksums, snippets, task_manager, mongodb_backups")
	config.Plugins = prompt(fmt.Sprintf("Enter plugins list [%s]", config.Plugins), config.Plugins)

	if !config.UseExistentPMM {
		ans := prompt("Create PMM Container? [y/N]", "N")
		config.CreatePMM = strings.ToLower(ans) == "y"
	}

	if !config.CreatePMM {
		fmt.Println("\n--- External PMM Configuration ---")
		config.PmmUser = prompt(fmt.Sprintf("PMM User [%s]", "admin"), "admin")
		if config.PmmPass == "" {
			config.PmmPass = promptPassword("PMM Password")
		}
		if config.PmmToken == "" {
			config.PmmToken = promptPassword("PMM Service Account Token")
		}
	}
}

func runSummaryScreen() {
	printBanner()
	fmt.Println("--- Configuration Summary ---")
	fmt.Printf("Install Dir: %s\n", config.InstallDir)
	fmt.Printf("Create PMM:  %v\n", config.CreatePMM)
	fmt.Printf("Plugins:     %s\n", config.Plugins)
	fmt.Printf("HTTP Port:   %s\n", config.HttpPort)
	fmt.Printf("HTTPS Port:  %s\n", config.HttpsPort)
	fmt.Println("-----------------------------")

	ans := prompt("Proceed with installation? [Y/n]", "Y")
	if strings.ToLower(ans) == "n" {
		fmt.Println("Installation cancelled.")
		os.Exit(1)
	}
}

func generateSecrets() map[string]string {
	secrets := map[string]string{
		"CASDOOR_DEFAULT_ORG_SALT":      randHex(8),
		"CASDOOR_SEP_ORG_SALT":          randHex(8),
		"CASDOOR_DEFAULT_CLIENT_ID":     randHex(10),
		"CASDOOR_DEFAULT_CLIENT_SECRET": randHex(20),
		"CASDOOR_SEP_CLIENT_ID":         randHex(10),
		"CASDOOR_SEP_CLIENT_SECRET":     randHex(20),
		"CASDOOR_DEFAULT_ADMIN_PASSWD":  randHex(20),
		"CASDOOR_SEP_ADMIN_PASSWD":      randHex(20),
		"CASDOOR_SEP_SEP_PASSWD":        randHex(20),
		"SEP_BACKEND_DB_PASSWORD":       randHex(20),
		"GF_SECURITY_ADMIN_PASSWORD":    randHex(20),
		"SEP_PMM_URL_AUTH_ACCOUNT":      fmt.Sprintf("%s:%s", config.PmmUser, config.PmmPass),
		"SEP_PMM_URL_AUTH_TOKEN":        config.PmmToken,
		"INSTALL_DIR":                   config.InstallDir,
	}

	if secrets["SEP_PMM_URL_AUTH_ACCOUNT"] == ":" {
		secrets["SEP_PMM_URL_AUTH_ACCOUNT"] = "admin:admin"
	}
	if secrets["SEP_PMM_URL_AUTH_TOKEN"] == "" {
		secrets["SEP_PMM_URL_AUTH_TOKEN"] = "CHANGEME"
	}

	fmt.Printf("[%s✓%s] Secrets generated\n", Green, Reset)
	return secrets
}

func generateTLS(tempDir string, certList string, secrets map[string]string) {
	fmt.Printf("Generating TLS Certificates... ")
	certsDir := filepath.Join(tempDir, "certs")
	os.MkdirAll(certsDir, 0755)

	// Generate JWT RSA Key
	jwtKey, _ := rsa.GenerateKey(rand.Reader, 4096)
	jwtKeyBytes := x509.MarshalPKCS1PrivateKey(jwtKey)
	jwtKeyPEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: jwtKeyBytes})
	os.WriteFile(filepath.Join(certsDir, "sep_token_jwt_key.key"), jwtKeyPEM, 0444)

	jwtPubBytes, _ := x509.MarshalPKIXPublicKey(&jwtKey.PublicKey)
	jwtPubPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: jwtPubBytes})
	os.WriteFile(filepath.Join(certsDir, "sep_token_jwt_key.pem"), jwtPubPEM, 0444)

	secrets["SEP_CASDOOR_PRIVATE_KEY_JSON"] = strings.ReplaceAll(string(jwtKeyPEM), "\n", "\\n")
	secrets["SEP_CASDOOR_CERTIFICATE_JSON"] = strings.ReplaceAll(string(jwtPubPEM), "\n", "\\n")

	// Generate CA
	caKey, _ := ecdsa.GenerateKey(elliptic.P384(), rand.Reader)
	caTemplate := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "SEP Root CA"},
		NotBefore:             time.Now(),
		NotAfter:              time.Now().AddDate(1, 0, 0),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
		BasicConstraintsValid: true,
	}

	caBytes, _ := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caBytes})
	os.WriteFile(filepath.Join(certsDir, "sep-ca.pem"), caPEM, 0444)

	caKeyBytes, _ := x509.MarshalECPrivateKey(caKey)
	caKeyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: caKeyBytes})
	os.WriteFile(filepath.Join(certsDir, "sep-ca-key.pem"), caKeyPEM, 0444)

	// Generate Leaf Certs
	certs := strings.Split(certList, ",")
	for i, certName := range certs {
		certName = strings.TrimSpace(certName)
		if certName == "" {
			continue
		}

		leafKey, _ := ecdsa.GenerateKey(elliptic.P384(), rand.Reader)
		leafTemplate := &x509.Certificate{
			SerialNumber: big.NewInt(int64(i + 2)),
			Subject:      pkix.Name{CommonName: certName},
			NotBefore:    time.Now(),
			NotAfter:     time.Now().AddDate(1, 0, 0),
			KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
			ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
			DNSNames:     []string{"localhost", "sep", "*.sep", "inventory_api", "tasks_api", "app"},
			IPAddresses:  []net.IP{net.ParseIP("127.0.0.1")},
		}

		leafBytes, _ := x509.CreateCertificate(rand.Reader, leafTemplate, caTemplate, &leafKey.PublicKey, caKey)
		leafPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: leafBytes})
		os.WriteFile(filepath.Join(certsDir, fmt.Sprintf("%s-cert.pem", certName)), leafPEM, 0444)

		leafKeyBytes, _ := x509.MarshalECPrivateKey(leafKey)
		leafKeyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: leafKeyBytes})
		os.WriteFile(filepath.Join(certsDir, fmt.Sprintf("%s-cert-key.pem", certName)), leafKeyPEM, 0444)
	}

	fmt.Printf("\b[%s✓%s] Done\n", Green, Reset)
}

func renderTemplates(tempDir string, secrets map[string]string) {
	fmt.Printf("Rendering templates... ")

	files := []string{
		"casdoor_init.json",
		"nginx.conf",
		"compose.yaml",
		"settings.yaml",
	}

	replacements := buildReplacements(secrets)

	for _, filename := range files {
		// Read the file directly from the embedded filesystem
		data, err := templateFS.ReadFile("templates/" + filename)
		if err != nil {
			logFatalf("Failed to read embedded template %s: %v", filename, err)
		}
		content := string(data)

		// String replacements
		for k, v := range replacements {
			content = strings.ReplaceAll(content, k, v)
		}

		// Handle Compose Registry logic
		if filename == "compose.yaml" && config.ContainerRegistry != "docker.io" {
			content = strings.ReplaceAll(content, "docker.io/", config.ContainerRegistry+"/")
		}

		// Handle PMM block logic
		lines := strings.Split(content, "\n")
		var outLines []string
		inPmmBlock := false
		for _, line := range lines {
			if strings.Contains(line, "#---PMM---#") {
				inPmmBlock = !inPmmBlock
				continue
			}
			if !inPmmBlock || config.CreatePMM {
				outLines = append(outLines, line)
			}
		}

		os.WriteFile(filepath.Join(tempDir, filename), []byte(strings.Join(outLines, "\n")), 0644)
	}

	// Write .secrets file
	var secretsContent strings.Builder
	for k, v := range secrets {
		secretsContent.WriteString(fmt.Sprintf("%s=%s\n", k, v))
	}
	os.WriteFile(filepath.Join(tempDir, ".secrets"), []byte(secretsContent.String()), 0640)

	fmt.Printf("\b[%s✓%s] Done\n", Green, Reset)
}

func buildReplacements(secrets map[string]string) map[string]string {
	reps := map[string]string{
		"${SEP_HTTP_PORT}":          config.HttpPort,
		"${SEP_HTTPS_PORT}":         config.HttpsPort,
		"${INSTALL_DIR}":            config.InstallDir,
		"${SEP_PMM_PUBLIC_HOST}":    config.PmmPublicHost,
		"${SEP_PMM_PUBLIC_ADDRESS}": config.PmmPublicHost,
		"${SEP_PMM_PORT}":           config.PmmPort,
		"${SEP_PMM_FRONTEND}":       config.PmmFrontend,
		"${SEP_IMAGE_NAME}":         config.ImageName,
		"${SEP_IMAGE_TAG}":          config.ImageTag,
	}

	// Merge secrets into replacements
	for k, v := range secrets {
		reps["${"+k+"}"] = v
	}

	// Plugin Disable Markers
	allPlugins := []string{"schema_change", "archive", "backups", "checksums", "snippets", "task_manager", "mongodb_backups"}
	activePlugins := make(map[string]bool)
	for _, p := range strings.Split(config.Plugins, ",") {
		activePlugins[strings.TrimSpace(p)] = true
	}

	for _, p := range allPlugins {
		marker := "#"
		if activePlugins[p] {
			marker = ""
		}
		reps[fmt.Sprintf("${SEP_PLUGINS_%s_DISABLE}", strings.ToUpper(p))] = marker
	}

	return reps
}

func commitFiles(tempDir string) {
	os.MkdirAll(config.InstallDir, 0755)

	// Move all files from tempDir to config.InstallDir
	entries, err := os.ReadDir(tempDir)
	if err != nil {
		logFatalf("Failed to read temp directory: %v", err)
	}

	for _, entry := range entries {
		src := filepath.Join(tempDir, entry.Name())
		dst := filepath.Join(config.InstallDir, entry.Name())

		// If dst exists, remove it first
		os.RemoveAll(dst)
		if err := os.Rename(src, dst); err != nil {
			logFatalf("Failed to move file %s to %s: %v", src, dst, err)
		}
	}
	fmt.Printf("[%s✓%s] Files committed to %s\n", Green, Reset, config.InstallDir)
}

func pullAndStart() {
	cmdArgs := []string{"compose", "--file", filepath.Join(config.InstallDir, "compose.yaml"), "--project-name", "sep"}
	imageRef := fmt.Sprintf("%s:%s", config.ImageName, config.ImageTag)

	// Docker Login & Pull
	if strings.HasPrefix(config.ImageName, "docker.io") && !strings.HasPrefix(config.ImageName, "docker.io/library/") {
		err := exec.Command(config.Engine, "pull", imageRef).Run()
		if err != nil {
			fmt.Printf("[%sINFO%s] Public pull failed. Trying to log in...\n", Cyan, Reset)
			if config.NoInteraction && config.DockerToken == "" {
				logFatalf("Image pull failed and interaction is disabled. Provide --docker-token.")
			}

			if config.DockerToken == "" {
				config.DockerToken = promptPassword("Docker Token")
			}

			loginCmd := exec.Command(config.Engine, "login", "--username", "percona", "--password-stdin", strings.Split(config.ImageName, "/")[0])
			loginCmd.Stdin = strings.NewReader(config.DockerToken)
			if err := loginCmd.Run(); err != nil {
				logFatalf("Registry login failed: %v", err)
			}
			fmt.Printf("[%s✓%s] Authenticated to %s\n", Green, Reset, strings.Split(config.ImageName, "/")[0])

			runCmdWithSpinner("Pulling SEP image", config.Engine, "pull", imageRef)
		} else {
			fmt.Printf("[%s✓%s] Image pulled: %s\n", Green, Reset, imageRef)
		}
	} else {
		runCmdWithSpinner("Pulling SEP image", config.Engine, "pull", imageRef)
	}

	// Create Containers
	upArgs := append(cmdArgs, "up", "--detach", "--no-start", "--remove-orphans")
	if err := runCmdWithSpinner("Creating containers", config.Engine, upArgs...); err != nil {
		logFatalf("Failed to create containers: %v", err)
	}

	engineCmd := fmt.Sprintf("%s compose --file %s/compose.yaml --project-name sep", config.Engine, config.InstallDir)

	if config.Autostart {
		startArgs := append(cmdArgs, "start")
		if err := runCmdWithSpinner("Starting Stack", config.Engine, startArgs...); err != nil {
			logFatalf("Failed to start stack: %v", err)
		}
		printBanner()
		fmt.Printf("\n%sInstallation Complete: SEP started!%s\n\n", Bold+Green, Reset)
		fmt.Printf("To watch logs, run:\n  %s logs -f\n\n", engineCmd)
		fmt.Printf("To stop the stack, run:\n  %s down\n\n", engineCmd)
	} else {
		printBanner()
		fmt.Printf("\n%sInstallation Complete!%s\n\n", Bold+Green, Reset)
		fmt.Printf("To start the stack, run:\n  %s start\n\n", engineCmd)
		fmt.Printf("To watch logs, run:\n  %s logs -f\n\n", engineCmd)
	}

	fmt.Println("==============================")
	fmt.Println("   SEP Access & Credentials   ")
	fmt.Println("==============================")
	fmt.Printf("\nAccess Interface: %shttps://localhost:%s%s\n\n", Bold, config.HttpsPort, Reset)
	fmt.Printf("Credentials stored in: %s/.secrets\n", config.InstallDir)
	fmt.Println("Run the following to retrieve your passwords:")
	fmt.Printf("%sAdmin User (admin):%s\n", Cyan, Reset)
	fmt.Printf("sed -n 's/^CASDOOR_SEP_ADMIN_PASSWD=//p' \"%s/.secrets\"\n\n", config.InstallDir)
	fmt.Printf("%sStandard User (sep):%s\n", Cyan, Reset)
	fmt.Printf("sed -n 's/^CASDOOR_SEP_SEP_PASSWD=//p' \"%s/.secrets\"\n", config.InstallDir)
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

func prompt(label, defaultVal string) string {
	reader := bufio.NewReader(os.Stdin)
	fmt.Printf("%s: ", label)
	input, _ := reader.ReadString('\n')
	input = strings.TrimSpace(input)
	if input == "" {
		return defaultVal
	}
	return input
}

func promptPassword(label string) string {
	fmt.Printf("%s: ", label)

	// Try to disable echo via stty (works on most Unix systems)
	exec.Command("stty", "-F", "/dev/tty", "-echo").Run()

	reader := bufio.NewReader(os.Stdin)
	input, _ := reader.ReadString('\n')

	// Re-enable echo
	exec.Command("stty", "-F", "/dev/tty", "echo").Run()
	fmt.Println()

	return strings.TrimSpace(input)
}

func runCmdWithSpinner(title, name string, args ...string) error {
	fmt.Printf("%s... ", title)
	stop := make(chan bool)
	go func() {
		spinChars := []rune{'-', '\\', '|', '/'}
		i := 0
		for {
			select {
			case <-stop:
				return
			default:
				fmt.Printf("\b%c", spinChars[i%len(spinChars)])
				i++
				time.Sleep(100 * time.Millisecond)
			}
		}
	}()

	cmd := exec.Command(name, args...)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	err := cmd.Run()

	stop <- true
	fmt.Print("\b \b") // Clear spinner char

	if err != nil {
		fmt.Printf("\b[%s✗%s] Failed\n", Red, Reset)
		fmt.Println(out.String())
		return err
	}
	fmt.Printf("\b[%s✓%s] Done\n", Green, Reset)
	return nil
}

func randHex(n int) string {
	b := make([]byte, n)
	_, err := rand.Read(b)
	if err != nil {
		logFatalf("Failed to generate random bytes: %v", err)
	}
	return hex.EncodeToString(b)
}

func getEnvOrDefault(key, defaultVal string) string {
	if val, exists := os.LookupEnv(key); exists {
		return val
	}
	return defaultVal
}

func isWritable(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("path is not a directory")
	}
	testFile := filepath.Join(path, ".test-write")
	f, err := os.Create(testFile)
	if err != nil {
		return err
	}
	f.Close()
	os.Remove(testFile)
	return nil
}

func isEmptyDir(name string) (bool, error) {
	f, err := os.Open(name)
	if err != nil {
		return false, err
	}
	defer f.Close()

	_, err = f.Readdirnames(1)
	if err == io.EOF {
		return true, nil
	}
	return false, err
}

func logFatalf(format string, v ...any) {
	fmt.Printf("\n[%sERROR%s] "+format+"\n", append([]any{Red, Reset}, v...)...)
	os.Exit(1)
}
