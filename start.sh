#!/usr/bin/env bash
INSTALL_CONF_TEMPL=${2:-"install-config.yaml"}

if [[ -z ${CLUSTER_NAME} ]]; then
  # We don't have a cluster name. Take it from input
  CLUSTER_NAME=$1
fi

# If we still don't have a cluster name we could generate a random name
if [[ -z ${CLUSTER_NAME} ]]; then
  echo "Please specify a cluster name."
  echo "$0 <cluster_name> [template_file]"
  exit 1
fi


# Create a directory to keep all the cluster specific stuff in
mkdir ${CLUSTER_NAME}


## TODO: Could do a simple template format so we can substitute some secrets
# install_conf=$(eval "cat <<$(printf '\x04\x04\x04') ;
# $(cat ${INSTALL_CONF_TEMPL})
# ")
# 
# echo $install_conf 

# Copy the template locally while updating cluster_name
cat $INSTALL_CONF_TEMPL | sed 's/<cluster_name>/my-cluster/g' > ${CLUSTER_NAME}/install-config.yaml

# If we don't have openshift-install locally we need to get it
if [[ ! $(which openshift-install) ]]; then
  echo "In the future we'll install openshift-install for you, but for now get it yourself please"
  exit 1
fi

# Create cluster
openshift-install create cluster --dir ${CLUSTER_NAME}

## Now that the cluster is installed we can load the cloudpak

# First set the kubeconfig so we can communicate with the cluster
export KUBECONFIG=$(pwd)/${CLUSTER_NAME}/auth/kubeconfig

# Some settings should fit here

# Create the job that starts the inception installer
python install-cp4mcm.py

# The python script could likely stream the logs if desired.
# Alternatively we could use kubectl to stream the logs here
echo "The install job should be running now."
echo "Check status with kubectl -n kube-system get jobs -l app=mcm-installer"
echo "To stream installer logs do kubectl -n kube-system logs $(kubectl -n kube-system get pods -l app=mcm-installer -o jsonpath='{.items[].metadata.name}')"
