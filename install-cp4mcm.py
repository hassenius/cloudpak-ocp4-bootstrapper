#!/usr/bin/env python
# This python creates a kubernetes job that performs the installation on IBM CloudPak for MCM
from kubernetes import client
from kubernetes import config as kubeconf
from kubernetes.client.rest import ApiException
from base64 import b64encode
import uuid

import os, json, yaml, sys, argparse

JOB_NAME = "mcm-installer"
CONFIG_FILE="./config.yaml" # Defaul config file if no input provided
DEFAULT_NODES=3

# Parse the arguments
parser = argparse.ArgumentParser(description='Create install job for IBM Cloud Pak.')
parser.add_argument('-f', dest='conf_file',
                    help='file to parse as config.yaml. "-" to read stdin kubectl style')
parser.add_argument('-d', dest='working_directory',
                    help='Working directory. Useful when saving copy of config.yaml')            
parser.add_argument('-s', dest='save_copy', action='store_true', help='Save copy of config.yaml used')
parser.add_argument('-n', dest='nodes',
                    help='Number of nodes to dedicate for the cloud pak. Default: %i' % DEFAULT_NODES)

args = parser.parse_args()

SAVE_COPY=args.save_copy
WDIR=args.working_directory
if args.conf_file:
    conf_file=args.conf_file
else:
    conf_file=CONFIG_FILE
    

# Accept getting config.yaml passed or piped to us kubectl style
if conf_file == '-':
    try:
        config = yaml.safe_load(sys.stdin) 
    except yaml.YAMLERROR as e:
        print("Problems parsing config from stdin")
        print(e)
else:
    if not os.path.exists(conf_file):
        print("Could not find config file '%s'" % conf_file)
        exit(1)
    if os.stat(conf_file).st_size == 0:
      print("Warning: config from %s file is empty" % conf_file)
    else:
      with open(conf_file, 'r') as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as e:
            print("Problems parsing %s" % conf_file)
            print(e)

# Allow any override from os environment
for k in os.environ:
    if k[:3] == 'MC_':
        config[k[3:]] = os.environ[k]

# Set number of dedicated nodes to use.
# Use DEFAULT_NODE if not provided through config file or environment variable
config['depl']['nodes'] = (args.nodes and args.nodes) or (not 'nodes' in config['depl'] and DEFAULT_NODES) or config['depl']['nodes']

# Generate a random admin password if none is set
if not 'default_admin_password' in config:
    config['default_admin_password'] = str(uuid.uuid1().hex)

## Construct the installation command
def install_command():
    # Constructs the install command array
    inst = []
    
    inst.append('ansible-playbook')
    
    # Append the node map
    inst.append('-e')
    inst.append(str(get_dedicated_nodes(num_nodes=config['depl']['nodes'])))
    
    # Append the setting from config.yaml OS environment
    inst.append('-e')
    inst.append(str(config))
    
    # Append the playbook
    inst.append('playbook/addon.yaml')
    
    return inst

## Get dedicated nodes for the CloudPak and construct entry for config.yaml
def get_dedicated_nodes(num_nodes=3,prefer_multizone=True):
    
    # Get list of nodes
    nodes = get_node_names(num_nodes=num_nodes,prefer_multizone=prefer_multizone)
    
    # Data structure
    n={}
    n["cluster_nodes"]               = {}
    n["cluster_nodes"]["master"]     = nodes
    n["cluster_nodes"]["proxy"]      = nodes
    n["cluster_nodes"]["management"] = nodes
    
    return n
    
    
## STUB    
def get_node_names(num_nodes=3,prefer_multizone=True):
    
    api_client = client.CoreV1Api()
    
    # Get list of nodes
    candidates=[]
    nodes = api_client.list_node().to_dict()
    for n in nodes['items']:
        if 'node-role.kubernetes.io/worker' in n['metadata']['labels']:
            # TODO: Check for label failure-domain.beta.kubernetes.io/zone and attempt to select from different azs
            candidates.append(n['metadata']['name'])
    
    # Return the requested number of nodes
    return candidates[:num_nodes]
    
    
def create_job_object(container_image, image_pull_secret=None,service_account_name=None):
    
    pull_secret = client.V1LocalObjectReference(
        name=image_pull_secret
    )
    # Configureate Pod template container
    container = client.V1Container(
        name="installer",
        image=container_image,
        command=list(install_command()))
    # Create and configurate a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "mcm-installer"}),
        spec=client.V1PodSpec(restart_policy="Never", containers=[container],
                                image_pull_secrets=[pull_secret],service_account_name=service_account_name))
    # Create the specification of deployment
    spec = client.V1JobSpec(
        template=template,
        backoff_limit=1)
    # Instantiate the job object
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=JOB_NAME),
        spec=spec)

    return job

def create_job(api_instance, job):
    api_response = api_instance.create_namespaced_job(
        body=job,
        namespace="kube-system")
    print("Job created. status='%s'" % str(api_response.status))

# Create a service account that the inception installer will run as
def create_service_account(name, namespace):
    print("Creating service account {} in {}".format(name, namespace))
    try:
        api = client.CoreV1Api()
        service_account = api.create_namespaced_service_account(
            namespace,
            {
                'apiVersion': 'v1',
                'kind': 'ServiceAccount',
                'metadata': {
                    'name': name,
                    'namespace': namespace,
                },
            }
        )

        return service_account.metadata.name
    except ApiException as e:
        if e.status == 409:
            # Already exists
            return name
        else:
            raise e 

    
def create_cluster_role_binding(name, user_name, namespace, role="cluster-admin"):
    print("Creating role binding of {} for {}".format(role, user_name))
    try:
        api = client.RbacAuthorizationV1Api()
        # TODO: Use generateName when it doesn't throw an exception
        api.create_cluster_role_binding(
            {
                'apiVersion': 'rbac.authorization.k8s.io/v1',
                'kind': 'ClusterRoleBinding',
                'metadata': {
                    'name': name,
                },
                'roleRef': {
                    'apiGroup': 'rbac.authorization.k8s.io',
                    'kind': 'ClusterRole',
                    'name': role,
                },
                'subjects': [{
                    'kind': 'ServiceAccount',
                    'name': user_name,
                    'namespace': namespace
                }]
            }
        )
        return name
        
    except ApiException as e:
        if e.status == 409:
            print("ClusterRolebinding already exists")
            # Already exists
            return name
        else:
            raise e
    except Exception as e:
        raise e


def create_pull_secret(name, namespace, server, username, password):
    print("Creating image pull secret {} in {}".format(name, namespace))
    
    # Construct the docker config.json file format
    auth={
        "auths":{
            server:{
                "username":username,
                "password":password,
                "auth":b64encode('%s:%s'.encode("utf-8") % (username.encode("utf-8"), password.encode("utf-8"))).decode("ascii")
            }
        }
    }

    try:
        api = client.CoreV1Api()
        metadata = client.V1ObjectMeta(
            name=name,
            namespace=namespace,
        )

        body = client.V1Secret(
            kind="Secret",
            type="kubernetes.io/dockerconfigjson",
            metadata=metadata,
            string_data = {
                ".dockerconfigjson":json.dumps(auth)
            }
            
        )
        r=api.create_namespaced_secret(
            namespace=namespace,
            body=body
        )
        return r
    except ApiException as e:
        # Catch kubernetes errors
        if e.status == 409:
            # Already Exists
            return name
        else:
            print("Error creating secret")
            raise e
    except Exception as e:
        # Catch normal programming errors
        raise e


def set_kubeapi_url():
    api = client.CoreV1Api()
    
    # Get the configmap
    cm = api.read_namespaced_config_map('console-config', 'openshift-console')
    
    # Load the console config yaml
    cc = yaml.safe_load(cm.data['console-config.yaml'])
    
    # Set the public API
    config['external_kube_apiserver'] = cc['clusterInfo']['masterPublicURL']
    
    return True

## STUBS ##

## If we want to have the ability to wait for the pod to start successfully
def wait_for_pod_running(pod, namespace):
    
    api = client.CoreV1Api()
    count = 10
    w = watch.Watch()
    for event in w.stream(api_instance.read_namespaced_pod_status(name, namespace), timeout_seconds=10):
        print("Event: %s %s" % (event['type'], event['object'].metadata.name))
        count -= 1
        if not count:
            w.stop()
    print("Finished namespace stream.")  
    
def get_job_pod_name():
    api = client.CoreV1Api()
    namespace = 'namespace_example' # str | object name and auth scope, such as for teams and projects
    pretty = 'pretty_example' # str | If 'true', then the output is pretty printed. (optional)
    _continue = '_continue_example' # str | The continue option should be set when retrieving more results from the server. Since this value is server defined, kubernetes.clients may only use the continue value from a previous query result with identical query parameters (except for the value of continue) and the server may reject a continue value it does not recognize. If the specified continue value is no longer valid whether due to expiration (generally five to fifteen minutes) or a configuration change on the server, the server will respond with a 410 ResourceExpired error together with a continue token. If the kubernetes.client needs a consistent list, it must restart their list without the continue field. Otherwise, the kubernetes.client may send another list request with the token received with the 410 error, the server will respond with a list starting from the next key, but from the latest snapshot, which is inconsistent from the previous list results - objects that are created, modified, or deleted after the first list request will be included in the response, as long as their keys are after the \"next key\".  This field is not supported when watch is true. Clients may start a watch from the last resourceVersion value returned by the server and not miss any modifications. (optional)
    field_selector = 'field_selector_example' # str | A selector to restrict the list of returned objects by their fields. Defaults to everything. (optional)
    label_selector = 'label_selector_example' # str | A selector to restrict the list of returned objects by their labels. Defaults to everything. (optional)
    limit = 56 # int | limit is a maximum number of responses to return for a list call. If more items exist, the server will set the `continue` field on the list metadata to a value that can be used with the same initial query to retrieve the next set of results. Setting a limit may return fewer than the requested amount of items (up to zero items) in the event all requested objects are filtered out and kubernetes.clients should only use the presence of the continue field to determine whether more results are available. Servers may choose not to support the limit argument and will return all of the available results. If limit is specified and the continue field is empty, kubernetes.clients may assume that no more results are available. This field is not supported if watch is true.  The server guarantees that the objects returned when using continue will be identical to issuing a single list call without a limit - that is, no objects created, modified, or deleted after the first request is issued will be included in any subsequent continued requests. This is sometimes referred to as a consistent snapshot, and ensures that a kubernetes.client that is using limit to receive smaller chunks of a very large result can ensure they see all possible objects. If objects are updated during a chunked list the version of the object that was present at the time the first list result was calculated is returned. (optional)
    resource_version = 'resource_version_example' # str | When specified with a watch call, shows changes that occur after that particular version of a resource. Defaults to changes from the beginning of history. When specified for list: - if unset, then the result is returned from remote storage based on quorum-read flag; - if it's 0, then we simply return what we currently have in cache, no guarantee; - if set to non zero, then the result is at least as fresh as given rv. (optional)
    timeout_seconds = 56 # int | Timeout for the list/watch call. This limits the duration of the call, regardless of any activity or inactivity. (optional)
    watch = true # bool | Watch for changes to the described resources and return them as a stream of add, update, and remove notifications. Specify resourceVersion. (optional)

    try: 
        api_response = api_instance.list_namespaced_pod(namespace, pretty=pretty, _continue=_continue, field_selector=field_selector, label_selector=label_selector, limit=limit, resource_version=resource_version, timeout_seconds=timeout_seconds, watch=watch)
        pprint(api_response)
    except ApiException as e:
        print("Exception when calling CoreV1Api->list_namespaced_pod: %s\n" % e)
        
## STUB -- if we want to follow the log from the inception installer
def follow_pod_log():
    api_instance = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient(configuration))
    name = 'name_example' # str | name of the Pod
    namespace = 'namespace_example' # str | object name and auth scope, such as for teams and projects
    container = 'container_example' # str | The container for which to stream logs. Defaults to only container if there is one container in the pod. (optional)
    follow = true # bool | Follow the log stream of the pod. Defaults to false. (optional)
    limit_bytes = 56 # int | If set, the number of bytes to read from the server before terminating the log output. This may not display a complete final line of logging, and may return slightly more or slightly less than the specified limit. (optional)
    pretty = 'pretty_example' # str | If 'true', then the output is pretty printed. (optional)
    previous = true # bool | Return previous terminated container logs. Defaults to false. (optional)
    since_seconds = 56 # int | A relative time in seconds before the current time from which to show logs. If this value precedes the time a pod was started, only logs since the pod start will be returned. If this value is in the future, no logs will be returned. Only one of sinceSeconds or sinceTime may be specified. (optional)
    tail_lines = 56 # int | If set, the number of lines from the end of the logs to show. If not specified, logs are shown from the creation of the container or sinceSeconds or sinceTime (optional)
    timestamps = true # bool | If true, add an RFC3339 or RFC3339Nano timestamp at the beginning of every line of log output. Defaults to false. (optional)

    try: 
        api_response = api_instance.read_namespaced_pod_log(name, namespace, container=container, follow=follow, limit_bytes=limit_bytes, pretty=pretty, previous=previous, since_seconds=since_seconds, tail_lines=tail_lines, timestamps=timestamps)
        pprint(api_response)
    except ApiException as e:
        print("Exception when calling CoreV1Api->read_namespaced_pod_log: %s\n" % e)
    
    
def main():
    # Configs can be set in Configuration class directly or using helper
    # utility. If no argument provided, the config will be loaded from
    # default location.
    kubeconf.load_kube_config()
    
    # Detect and set the external api url
    set_kubeapi_url()
    
    # Save the file for future reference if requested
    if SAVE_COPY:
        if WDIR:
            f=WDIR+"/config.yaml-used"
        else:
            f="config.yaml-used"
        with open(f, 'w') as of:
            yaml.safe_dump(config, of, explicit_start=True, default_flow_style = False)
            # Dump the node stuff as well
            yaml.safe_dump(get_dedicated_nodes(num_nodes=config['depl']['nodes']), of, explicit_start=False, default_flow_style = False )


    if config['private_registry_enabled']:
        print("Creating image pull secret for %s" % config['private_registry_server'])
        create_pull_secret(
            name="installer-pull-secret", 
            namespace="kube-system", 
            server=config['private_registry_server'], 
            username=config['docker_username'], 
            password=config['docker_password']
        )
        print("Done")
    
    # Make sure we have appropriate service account
    sa = create_service_account("mcm-deploy", "kube-system")
    
    rb = create_cluster_role_binding("mcm-deploy", sa, "kube-system")
        
    batch_v1 = client.BatchV1Api()
    
    # Create a job object with client-python API. 
    job = create_job_object(
            container_image=config['depl']['installer_image'],
            image_pull_secret="installer-pull-secret",
            service_account_name="mcm-deploy"
          )

    create_job(batch_v1, job)


if __name__ == '__main__':
    main()
