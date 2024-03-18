job "purge-table-sample-2" {
  datacenters = ["dc1"]
  type = "batch"
  constraint {
    attribute = "${node.unique.name}"
    value     = "platform-team16"
  }
  group "purge-task-group" {
    task "purge-task" {
      driver = "raw_exec"

      meta {
        host = "localhost"
        port = "3306"
        palias = "archive_bube_sample"
        sourcedb = "bube"
        sourcetable = "users"
        desttable = "users_archive"
        where = "last_login < CURDATE() - INTERVAL 6 MONTH"
        run_uuid = "${uuidv4()}"
      }

      template {
        destination = "local/purge_tables2.yml"
        data = <<-EOH
            ALL:
              SOURCE_HOST: {{ env "NOMAD_META_host" }}
              SOURCE_PORT: {{ env "NOMAD_META_port" }}
            PURGE_LIST:
            - ALIAS: {{ env "NOMAD_META_palias" }}
              SOURCE_DB: {{ env "NOMAD_META_sourcedb" }}
              SOURCE_TABLE: {{ env "NOMAD_META_sourcetable" }}
              DEST_TABLE: {{ env "NOMAD_META_desttable" }}
              WHERE: "{{ env "NOMAD_META_where" }}"
            EOH
      }

      config {
        command = "/home/percona/bin/purge-tables.py"
        args = [
          "-a{{ env "NOMAD_META_palias" }}",
          "-c${NOMAD_TASK_DIR}/purge_tables2.yml"
        ]
      }
    }
  }
}

