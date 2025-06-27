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

### 2. AWS
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
