# PBM Backup plugin

This plugin generates PBM backups using logical and physical methods.
It also allows complete PBM configuration.

## Pre-requisites

This plugin does not configure PBM environment It assumes PBM CLI is configured either on a Replica Set secondary node, or a config/mongoS node when sharding.

Essentialy, SEP should have access to a node that is able to run:

```
pbm status
pbm config
pbm backup
```

You also need to provide an s3 compatible endpoint, (minio for instance), and Access Key alongside credentials.

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
