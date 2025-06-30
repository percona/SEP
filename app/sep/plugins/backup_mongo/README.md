# PBM Backup plugin

This plugin generates PBM backups using logical and physical methods.
It also allows PBM configuration.
Restores are also supported for PHYSICAL backups.

## Pre-requisites


### 1. PSMDB

This plugin was tested with Debian 12
Any mongod version > 7.0 running with latest pbm should work
https://docs.percona.com/percona-server-for-mongodb/7.0/install/apt.html#procedure


### 2. PBM
https://docs.percona.com/percona-backup-mongodb/installation.html
This plugin does not configure PBM environment It assumes PBM CLI is configured either on a Replica Set secondary node, or a config/mongoS node when sharding.

Essentialy, SEP should have access to a Linux node that is able to run:

```
pbm status
pbm config
pbm backup
```

### 3. AWSCLI
If your target node needs read or write access to s3 buckets
You also need to provide an s3 compatible endpoint, (minio for instance)


Access Key alongside credentials should be available on Linux node:

```
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws configure
```

In a demo environment, please follow:
https://min.io/docs/minio/linux/integrations/aws-cli-with-minio.html

Please make sure your pbm configuration looks similar to this block:

```
$ pbm config
storage:
  type: s3
  s3:
    region: us-east-1
    endpointUrl: http://192.168.0.47:9000/
    forcePathStyle: true
    bucket: pbm-physical
    prefix: data/pbm/backup
    credentials:
      access-key-id: '***'
      secret-access-key: '***'
    maxUploadParts: 10000
    storageClass: STANDARD
    insecureSkipTLSVerify: false
pitr:
  enabled: true
  compression: s2
backup:
  oplogSpanMin: 0
  compression: s2
restore: {}
```

Please check PBM configuration documentation for more details:

https://docs.percona.com/percona-backup-mongodb/install/initial-setup.html

### 2. PBM Helper script.

Backup, Config and Restore features rely on the following variables that contain filepaths with corresponding scripts:


```
PBM_CREATE_PHYSICAL=/home/percona/bin/pbm_create_physical.sh
PBM_CREATE_LOGICAL=/home/percona/bin/pbm_create_logical.sh
PBM_CREATE_CONFIG=/home/percona/bin/pbm_create_config.sh
PBM_CREATE_RESTORE=/home/percona/bin/pbm_create_restore.sh
```

Is is imperative that such variables are properly exported un nomad agent's client node.

Here is a sample of what each script shoud contain:

```
# pbm_create_config.sh
echo "$PBM_CONFIG_YAML" | docker compose exec -T $SERVICE_NAME pbm config --file="-"


# pbm_create_restore.sh
sudo systemctl stop pbm-agent
sudo systemctl stop mongod
sudo rm -rf $LOCAL_DBPATH
sudo aws --endpoint-url http://192.168.0.47:9000 s3 cp s3://pbm-physical/data/pbm/backup/$BACKUP_NAME/ --recursive
curl -OL https://go.dev/dl/go1.24.0.linux-amd64.tar.gz
tar -xzf go1.24.0.linux-amd64.tar.gz
cd go/bin/
./go install github.com/klauspost/compress/s2/cmd/s2c@latest
DATAFILES=$(find $LOCAL_DBPATH -type f -name '*.s2')
for file in $DATAFILES; do
  sudo ~/go/bin/s2d --rm "$file"
done > /tmp/s2d_out.txt 2>&1
sudo chown -R mongod:mongod
sudo systemctl start mongod
sudo systemctl start pbm-agent
```