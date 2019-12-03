#!/usr/bin/env bash
function show_help() {
  echo "Usage"
  echo "$0 -n <cluster_name> [-d <domain_name>] [-t openshift-install.yaml-template] [-c config.yaml-template] [-s]"
  
}

while getopts "h?n:d:t:c:s" opt; do
    case "$opt" in
    h|\?)
        show_help
        exit 0
        ;;
    n)
        CLUSTER_NAME=$OPTARG
        ;;
    d)
        DOMAIN_NAME=$OPTARG
        ;;
    t)  
        INSTALL_CONF_TEMPL=$OPTARG
        ;;
    c)  
        CONFIG_YAML=$OPTARG
        ;;
    s)
        SAVE_COPY=1
    esac
done

# If we still don't have a cluster name we could generate a random name
if [[ -z ${CLUSTER_NAME} ]]; then
  echo "ERROR: Please specify a cluster name."
  show_help
  exit 1
fi


if [[ -z ${INSTALL_CONF_TEMPL} ]]; then
  INSTALL_CONF_TEMPL="./install-config.yaml"
fi
# Create a directory to keep all the cluster specific stuff in
mkdir clusters/${CLUSTER_NAME}


echo "Install config ${INSTALL_CONF_TEMPL}"

# Copy the template locally while updating cluster_name
cat $INSTALL_CONF_TEMPL | sed "s/<cluster_name>/$CLUSTER_NAME/g ; s/<domain_name>/$DOMAIN_NAME/g" > ${CLUSTER_NAME}/install-config.yaml

# If desired create a copy of the template
if [[ ! -z ${SAVE_COPY} ]]; then
  cat $INSTALL_CONF_TEMPL | sed "s/<cluster_name>/$CLUSTER_NAME/g ; s/<domain_name>/$DOMAIN_NAME/g" > ${CLUSTER_NAME}/install-config.yaml-backup
fi

# If we don't have openshift-install locally we need to get it
if [[ ! $(which openshift-install) ]]; then
  echo "In the future we'll install openshift-install for you, but for now get it yourself please"
  exit 1
fi

# Create cluster
openshift-install create cluster --dir clusters/${CLUSTER_NAME}

## Now that the cluster is installed we can load the cloudpak

# First set the kubeconfig so we can communicate with the cluster
export KUBECONFIG=$(pwd)/clusters/${CLUSTER_NAME}/auth/kubeconfig

# Create proper certificates
echo "Generating valid certificates using acme.sh"
CERT_DIR="clusters/${CLUSTER_NAME}/certs"
mkdir -p ${CERT_DIR}
export LE_API=$(oc whoami --show-server | cut -f 2 -d ':' | cut -f 3 -d '/' | sed 's/-api././')
export LE_WILDCARD=$(oc get ingresscontroller default -n openshift-ingress-operator -o jsonpath='{.status.domain}')
acme.sh/acme.sh --issue -d ${LE_API} -d *.${LE_WILDCARD} --dns dns_aws

acme.sh/acme.sh --install-cert -d ${LE_API} -d *.${LE_WILDCARD} --cert-file ${CERT_DIR}/cert.pem --key-file ${CERT_DIR}/key.pem --fullchain-file ${CERT_DIR}/fullchain.pem --ca-file ${CERT_DIR}/ca.cer

oc create secret tls router-certs --cert=${CERT_DIR}/fullchain.pem --key=${CERT_DIR}/key.pem -n openshift-ingress
oc patch ingresscontroller default -n openshift-ingress-operator --type=merge --patch='{"spec": { "defaultCertificate": { "name": "router-certs" }}}'


# Create the job that starts the inception installer
python install-cp4mcm.py ${CONFIG_YAML:+-f} ${CONFIG_YAML} ${SAVE_COPY:+-s} ${SAVE_COPY:+-d} ${SAVE_COPY:+clusters/$CLUSTER_NAME}

# The python script could likely stream the logs if desired.
# Alternatively we could use kubectl to stream the logs here
echo "The install job should be running now."
echo "Check status with kubectl -n kube-system get jobs -l app=mcm-installer"
echo "To stream installer logs do kubectl -n kube-system logs $(kubectl -n kube-system get pods -l app=mcm-installer -o jsonpath='{.items[].metadata.name}')"
