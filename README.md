# CloudPak Bootstrapper

This is a simple process that defines a flow for installing OCP 4 using the OpenShift Installer and the IBM CloudPak inception image to install the relevant CloudPak.

## Requirements

To use this automated workflow you require the following
* Openshift 4 Requirements:
  * `openshift-install` tool installed
  * OpenShift pull secret
  * Cloud credentials
  * Domain in your control
* IBM CloudPak requirements
  * CloudPak available from private registry
  * `kubectl` cli tool installed
  * python with kubernetes client library

  
  ## How to use
  
  1. Clone this repository
  2. Create a `install-config.yaml` as template for the `openshift-install` tool (instructions below)
  3. Create a `config.yaml` for the CloudPak installer
  4. Run `./start.sh -n <cluster_name> -d <domain>  [template_file]`
      Where `<cluster_name>` is the name of the cluster to create, and `template_file` is optionally which template to use in the case you have multiple templates, or the file is called something else than `./install-config.yaml`

  ### What happens next?
  
  The script will 
  - create a directory structure under `./clusters` named the same as the `<domain>/<cluster_name>` you specified 
  - copy the `install-config.yaml` you specified there while updating the cluster name and domain name
  - start `openshift-install`
  - create valid wildcard certificates for `*.apps.<domain>` using letsencrypt
  - create a kubernetes job for the CloudPak installer with the config specified in config.yaml

  
  
### install-config.yaml setup

The install-config.yaml is configured as specified here [https://docs.openshift.com/container-platform/4.2/installing/installing_aws/installing-aws-customizations.html](https://docs.openshift.com/container-platform/4.2/installing/installing_aws/installing-aws-customizations.html)

The only exception is that this bootstrapper will update the cluster name and basedomain before starting the installer

Here's an example `install-config.yaml`

```
apiVersion: v1

baseDomain: <domain_name> # You must leave this intact so script can replace 
metadata:
  name: <cluster_name> # You must leave this intact so script can replace

compute:
- hyperthreading: Enabled
  name: worker
  platform:
    aws:
      type: m5.2xlarge
      rootVolume:
        size: 128
      zones:
      - eu-west-1a
      - eu-west-1b
      - eu-west-1c
  replicas: 3

controlPlane:
  hyperthreading: Enabled
  name: master
  platform:
    aws:
      type: m5.xlarge
      rootVolume:
        size: 128
      zones:
      - eu-west-1a
      - eu-west-1b
      - eu-west-1c
  replicas: 3

networking:
  clusterNetwork:
  - cidr: 10.128.0.0/14
    hostPrefix: 23
  machineCIDR: 10.0.0.0/16
  networkType: OpenShiftSDN
  serviceNetwork:
  - 172.30.0.0/16

platform:
  aws:
    region: eu-west-1
    userTags:
      owner: testuser
      tags: are_applied_to_all_resources
      team: ICPMCM
      Usage: Temp


pullSecret: '{"auths":{"cloud.openshift.com":...etc...insert_your_own}}}'
sshKey: |
  ssh-rsa AAAAB3....etc....LBls== sshkey1
  ssh-rsa AAAAB3....etc....CBbQ== sshkey2
```
See Openshift documentation for more information


### config.yaml setup

The `config.yaml` file is provided to the IBM CloudPak installer as is.
The only differences are:
1. You do not have to provide named dedicated nodes for the installer. The installer auto-detects this and populates the relevant sections
2. You must also specify an `depl.installer_image` key for the CloudPak installer. It is assumed that the installer (i.e. `icp-inception`) is located on the same private registry as the rest of the CloudPak images, so the same authentication information will be reused.
3. Any environment environment variable named `MC_` will be added as a key, overwriting or adding to the existing `config.yaml`. This follows a similar model to Terraforms `TF_VAR_` environment variables.


Example config.yaml
```
## This entry is only for this installation flow
depl:
  installer_image: my-private-registry.com/ibmcom/icp-inception:3.2.2
  nodes: 3 # optional, how many nodes to dedicate to the cloud pak. Default: 3

## The rest is the normal config.yaml passed into the inception installer

#### NOTE 
#### We do not need to provide a cluster_nodes section. 
#### This will be generated for us

storage_class: gp2

# Private registry stuff for the CloudPak images
private_registry_enabled: true
private_registry_server: my-private-registry.com
image_repo: my-private-registry.com/ibmcom-amd64
docker_username: <my_username>
docker_password: <my_secret_password>

# Enable MCM
mcm_enabled: true

# Login details for the MCM Dashboard
## a random default_admin_password will be generated if not specified
default_admin_password: <my_secret_password>
default_admin_user: kubeadmin

# Enable HA mode for MCM ETCD
multicluster-hub:
  global:
    replicas: 3
  etcd:
    haMode: true
    persistence: true
    storageclassName: gp2
  core:
    apiserver:
      etcd:
        haMode: true
```
