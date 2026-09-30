from selenium import webdriver
from selenium.webdriver import FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import kubernetes as ks
from time import sleep
import os
import hashlib
import ipaddress
import json
import re

from kubernetes.client.exceptions import ApiException


class PortProvider:
    def __init__(self, protos=None):
        self.requires_ip = False
        self.allows_port_range = False
        self.protos = protos

        if self.protos is None:
            self.protos = ["TCP", "UDP"]

        if not hasattr(self, "base_name"):
            self.base_name = os.getenv("BASE_NAME", 'configure-ports')

        self.label_selector = os.getenv("LABEL_SELECTOR", f'{self.base_name}=1')
        self.annotation_keys = dict()
        self.config_maps_name = dict()
        self.auto_annotation_key = os.getenv("AUTO_ANNOTATION_KEY", f'{self.base_name}.auto')
        for proto in self.protos:
            self.annotation_keys[proto] = os.getenv(f"{proto}_ANNOTATION_KEY", f'{self.base_name}.{proto.lower()}-ports')
            self.config_maps_name[proto] = os.getenv(f"{proto}_CONFIG_MAP_NAME", f"{proto.lower()}-services")
        self.namespace = os.getenv("PORT_PROVIDER_NAMESPACE")

    def patch_ports(self, new_port_configs, old_port_configs):
        pass


class Router (PortProvider):
    def __init__(self, password=None, host="192.168.0.1", router_proto="http"):
        self.base_name = os.getenv("BASE_NAME", 'tplink-ports')
        super().__init__(protos=["ANY"])
        self.requires_ip = True
        self.allows_port_range = True
        self.delay = 5
        self.opts = FirefoxOptions()
        self.opts.add_argument("--headless")
        self.driver = None
        self.router_proto = os.getenv("ROUTER_PROTO", router_proto)
        self.host = os.getenv("ROUTER_HOST", host)
        self.password = os.getenv("ROUTER_PASSWORD", password)

    def execute_task(self, task, *args, **kwargs):
        with webdriver.Firefox(options=self.opts) as driver:
            self.driver = driver
            task(*args, **kwargs)
            self.driver = None

    def load_url(self, path=""):
        self.driver.get(f"{self.router_proto}://{self.host}{path}")

    def wait_for_object(self, object_type, object_value):
        try:
            return WebDriverWait(self.driver, self.delay).until(EC.presence_of_element_located((object_type, object_value)))
        except TimeoutException:
            print(f"Loading took too much time! Element {object_type} - {object_value}.")
            return None

    def get_element_by_custom_attribute(self, attribute_name, attribute_value, html_element=None):
        if html_element is None:
            return self.wait_for_object(By.CSS_SELECTOR, f"[{attribute_name}='{attribute_value}']")
        else:
            return html_element.find_element(By.CSS_SELECTOR, f"[{attribute_name}='{attribute_value}']")

    def get_element_by_classes(self, classes, html_element=None):
        if html_element is None:
            return self.wait_for_object(By.XPATH, f"//*[contains(@class, '{classes}')]")
        else:
            return html_element.find_element(By.XPATH, f"//*[contains(@class, '{classes}')]")

    def click_object(self, html_element=None, object_type=None, object_value=None):
        if html_element is None:
            self.driver.execute_script("arguments[0].click();", self.wait_for_object(object_type, object_value))
        else:
            self.driver.execute_script("arguments[0].click();", html_element)

    def set_value(self, value, html_element=None, object_type=None, object_value=None):
        if html_element is None:
            self.driver.execute_script(f'arguments[0].value="{value}"', self.wait_for_object(object_type, object_value))
        else:
            self.driver.execute_script(f'arguments[0].value="{value}"', html_element)
        self.click_object(html_element)

    def login(self):
        login_input = self.get_element_by_classes('text-text password-text password-hidden')

        login_input.send_keys(self.password)
        login_input.send_keys(Keys.RETURN)

    def logout(self):
        self.click_object(self.get_element_by_classes('icon button-icon logout-button'))
        self.click_object(self.get_element_by_classes('text button-text'))

    def __add_port(self, service_name, service_ip, service_external_port, service_internal_port=None):
        self.load_url("/#portForwarding")

        self.login()

        self.click_object(self.get_element_by_classes('operation-btn btn-add fst lst'))

        elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.SERVICE_NAME}').find_element(By.CSS_SELECTOR, "input[type='text']")
        self.set_value(service_name, elem)

        elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.DEVICE_IP_ADDRESS}').find_element(By.CSS_SELECTOR, "input[type='text']")
        self.set_value(service_ip, elem)

        elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.EXTERNAL_PORT}').find_element(By.CSS_SELECTOR, "input[type='text']")
        self.set_value(service_external_port, elem)

        if service_internal_port is not None:
            elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.INTERNAL_PORT}').find_element(By.CSS_SELECTOR, "input[type='text']")
            self.set_value(service_internal_port, elem)

        self.click_object(self.wait_for_object(By.ID, "port-forwarding-grid-save-button").find_element(By.CLASS_NAME, "button-button"))

        self.logout()

    def __delete_port(self, service_name):
        self.load_url("/#portForwarding")

        self.login()

        port_element = self.wait_for_object(By.XPATH, f"//*[td/div/div = '{service_name}']")
        counter = 1
        while port_element is None:
            self.click_object(self.get_element_by_classes(f'paging-btn paging-btn-num pageing-btn-{counter}'))
            port_element = self.wait_for_object(By.XPATH, f"//*[td/div/div = '{service_name}']")
            counter += 1
        elem_key = port_element.get_attribute("data-key")
        self.click_object(self.driver.find_element(By.CSS_SELECTOR, f"a[data-key='{elem_key}'][class*='btn-delete']"))

        self.logout()

    def __add_ports(self, ports):
        self.load_url("/#portForwarding")

        self.login()

        for service_name, service_ip, service_external_port, service_internal_port in ports:

            self.click_object(self.get_element_by_classes('operation-btn btn-add fst lst'))

            elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.SERVICE_NAME}').find_element(By.CSS_SELECTOR, "input[type='text']")
            self.set_value(service_name, elem)

            elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.DEVICE_IP_ADDRESS}').find_element(By.CSS_SELECTOR, "input[type='text']")
            self.set_value(service_ip, elem)

            elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.EXTERNAL_PORT}').find_element(By.CSS_SELECTOR, "input[type='text']")
            self.set_value(service_external_port, elem)

            if service_internal_port is not None:
                elem = self.get_element_by_custom_attribute("label-field", '{PORT_FORWARDING.INTERNAL_PORT}').find_element(By.CSS_SELECTOR, "input[type='text']")
                self.set_value(service_internal_port, elem)

            self.click_object(self.wait_for_object(By.ID, "port-forwarding-grid-save-button").find_element(By.CLASS_NAME, "button-button"))

        self.logout()

    def __delete_ports(self, ports):
        self.load_url("/#portForwarding")

        self.login()

        for service_name in ports:

            port_element = self.wait_for_object(By.XPATH, f"//*[td/div/div = '{service_name}']")
            no_loop = True
            counter = 1
            next_button = self.get_element_by_classes(f'paging-btn paging-btn-num pageing-btn-{counter}')
            while port_element is None and no_loop:
                if next_button is None:
                    no_loop = False
                    counter = 0
                    next_button = self.get_element_by_classes(f'paging-btn paging-btn-num pageing-btn-{counter}')
                self.click_object(next_button)
                port_element = self.wait_for_object(By.XPATH, f"//*[td/div/div = '{service_name}']")
                counter += 1
            elem_key = port_element.get_attribute("data-key")
            self.click_object(self.driver.find_element(By.CSS_SELECTOR, f"a[data-key='{elem_key}'][class*='btn-delete']"))

        self.logout()

    def add_port(self, service_name, service_ip, service_external_port, service_internal_port=None):
        self.execute_task(self.__add_port, service_name, service_ip, service_external_port, service_internal_port)

    def delete_port(self, service_name):
        self.execute_task(self.__delete_port, service_name)

    def add_ports(self, ports):
        self.execute_task(self.__add_ports, ports)

    def delete_ports(self, ports):
        self.execute_task(self.__delete_ports, ports)

    def patch_ports(self, new_port_configs, old_port_configs):
        redundant_ports = old_port_configs.keys() - new_port_configs.keys()
        added_ports = new_port_configs.keys() - old_port_configs.keys()
        self.patch_router_ports(redundant_ports, added_ports, new_port_configs, old_port_configs)

    def patch_router_ports(self, redundant_ports, added_ports, NEW_CONFIGS, CONFIGS):
        redundant_names = [self.prepare_name(f'{CONFIGS[k].service.lower()}-{CONFIGS[k].proto.lower()}-{CONFIGS[k].port.split(":")[0]}') for k in redundant_ports]

        self.delete_ports(redundant_names)
        self.add_ports([(self.prepare_name(f'{NEW_CONFIGS[k].service.lower()}-{NEW_CONFIGS[k].proto.lower()}-{NEW_CONFIGS[k].port.split(":")[0]}'), NEW_CONFIGS[k].ip, NEW_CONFIGS[k].port.split(":")[0], int_p if (int_p := NEW_CONFIGS[k].port.split(":")[1]) != "" else None) for k in added_ports])

    @staticmethod
    def prepare_name(name):
        return "K" + name[-27:]


class Nginx (PortProvider):
    def __init__(self):
        self.base_name = os.getenv("BASE_NAME", 'ingress-nginx-ports')
        super().__init__(protos=["TCP", "UDP"])
        self.ingress_deployment = os.getenv("INGRESS_DEPLOYMENT", "ingress-nginx-controller")
        self.ingress_service = os.getenv("INGRESS_SERVICE", self.ingress_deployment)
        self.ingress_container_index = int(os.getenv("INGRESS_CONTAINER_INDEX", 0))

    def patch_ports(self, new_port_configs, old_port_configs):
        redundant_ports = old_port_configs.keys() - new_port_configs.keys()
        added_ports = new_port_configs.keys() - old_port_configs.keys()

        self.patch_ingress_deployment(redundant_ports, added_ports, new_port_configs, old_port_configs)
        for i in range(5):
            try:
                self.patch_ingress_service(redundant_ports, added_ports, new_port_configs, old_port_configs)
                break
            except Exception as e:
                if i == 4:
                    raise e
                sleep(10)
                continue

    def patch_ingress_deployment(self, redundant_ports, added_ports, NEW_CONFIGS, CONFIGS):
        v1_apps = ks.client.AppsV1Api()

        deployment = v1_apps.read_namespaced_deployment(name=self.ingress_deployment, namespace=self.namespace)
        deployment_ports = deployment.spec.template.spec.containers[self.ingress_container_index].ports
        redundant_indexes = sorted([deployment_ports.index(list(
            filter(lambda p: p.name == f'{CONFIGS[k].proto.lower()}-{CONFIGS[k].port.split(":")[0]}',
                   deployment_ports))[0])
                                    for k in redundant_ports], reverse=True)

        patch_remove = [
            {
                "op": "remove",
                "path": f'/spec/template/spec/containers/{self.ingress_container_index}/ports/{i}'
            }
            for i in redundant_indexes
        ]

        patch_add = [
            {
                "op": "add",
                "path": f'/spec/template/spec/containers/{self.ingress_container_index}/ports/-',
                "value": {"name": f'{NEW_CONFIGS[k].proto.lower()}-{NEW_CONFIGS[k].port.split(":")[0]}',
                          "protocol": f'{NEW_CONFIGS[k].proto}',
                          "containerPort": int(NEW_CONFIGS[k].port.split(":")[0])}
            }
            for k in added_ports
        ]

        patch = patch_remove + patch_add

        if len(patch) > 0:
            v1_apps.patch_namespaced_deployment(name=self.ingress_deployment, namespace=self.namespace, body=patch)

    def patch_ingress_service(self, redundant_ports, added_ports, NEW_CONFIGS, CONFIGS):
        v1 = ks.client.CoreV1Api()

        service = v1.read_namespaced_service(name=self.ingress_service, namespace=self.namespace)
        service_ports = service.spec.ports
        redundant_indexes = sorted([service_ports.index(
            list(filter(lambda p: p.name == f'{CONFIGS[k].proto.lower()}-{CONFIGS[k].port.split(":")[0]}',
                        service_ports))[
                0]) for k in redundant_ports], reverse=True)

        patch_remove = [
            {
                "op": "remove",
                "path": f'/spec/ports/{i}'
            }
            for i in redundant_indexes
        ]

        patch_add = [
            {
                "op": "add",
                "path": f'/spec/ports/-',
                "value": {"name": f'{NEW_CONFIGS[k].proto.lower()}-{NEW_CONFIGS[k].port.split(":")[0]}',
                          "protocol": f'{NEW_CONFIGS[k].proto}', "port": int(NEW_CONFIGS[k].port.split(":")[0]),
                          "targetPort": int(NEW_CONFIGS[k].port.split(":")[0])}
            }
            for k in added_ports
        ]

        patch = patch_remove + patch_add

        if len(patch) > 0:
            v1.patch_namespaced_service(name=self.ingress_service, namespace=self.namespace, body=patch)


class PodGateway(PortProvider):
    """
    MetalLB-backed L3/L4 gateway.

    API:

        labels:
          pod-ports: "1"

        annotations:
          pod-ports.any-ports: "2222:22"
          pod-ports.tcp-ports: "8443:443"
          pod-ports.udp-ports: "51820:51820"

    MetalLB owns a stable LAN IP.

    The gateway pod itself has only the ordinary Kubernetes eth0.

    An initContainer with NET_ADMIN installs nftables rules in the pod
    network namespace and exits. The main container has no capabilities,
    no Kubernetes API token and no listening userspace service.
    """

    CONFIG_HASH_ANNOTATION = "port-configurator.skabrits/config-sha256"

    def __init__(self):
        self.base_name = os.getenv("BASE_NAME", "pod-ports")
        super().__init__(protos=["TCP", "UDP", "ANY"])

        self.requires_ip = False
        self.allows_port_range = True

        if not self.namespace:
            raise ValueError(
                "PORT_PROVIDER_NAMESPACE must be set for PodGateway"
            )

        # Do not collide with Nginx/Router state ConfigMaps.
        for proto in self.protos:
            self.config_maps_name[proto] = os.getenv(
                f"{proto}_CONFIG_MAP_NAME",
                f"{self.base_name}-{proto.lower()}-services"
            )

        self.gateway_deployment = os.getenv(
            "GATEWAY_DEPLOYMENT",
            "pod-gateway"
        )

        self.gateway_config_prefix = os.getenv(
            "GATEWAY_CONFIG_PREFIX",
            "pod-gateway-rules"
        )

        self.gateway_service_prefix = os.getenv(
            "GATEWAY_SERVICE_PREFIX",
            "pod-gateway"
        )

        self.init_image = os.getenv(
            "GATEWAY_INIT_IMAGE",
            "skabrits/port-gateway-init:0.1.0"
        )

        self.pause_image = os.getenv(
            "GATEWAY_PAUSE_IMAGE",
            "registry.k8s.io/pause:3.10"
        )

        #
        # MetalLB
        #

        self.load_balancer_ip = os.environ[
            "GATEWAY_LOAD_BALANCER_IP"
        ]

        lb_ip = ipaddress.ip_address(self.load_balancer_ip)

        if lb_ip.version != 4:
            raise ValueError(
                "PodGateway currently supports an IPv4 "
                "MetalLB address only"
            )

        self.metallb_address_pool = os.getenv(
            "GATEWAY_METALLB_ADDRESS_POOL"
        )

        self.shared_ip_key = os.getenv(
            "GATEWAY_METALLB_SHARED_IP_KEY",
            f"{self.namespace}-{self.gateway_deployment}"
        )

        self.external_traffic_policy = os.getenv(
            "GATEWAY_EXTERNAL_TRAFFIC_POLICY",
            "Local"
        )

        if self.external_traffic_policy not in ["Local", "Cluster"]:
            raise ValueError(
                "GATEWAY_EXTERNAL_TRAFFIC_POLICY must be "
                "Local or Cluster"
            )

        self.allocate_node_ports = (
            os.getenv(
                "GATEWAY_ALLOCATE_NODE_PORTS",
                "0"
            ) == "1"
        )

        #
        # Allowed external range.
        #
        # This should correspond to the one large static rule on Archer.
        #

        self.port_min = int(
            os.getenv("GATEWAY_PORT_MIN", "1")
        )

        self.port_max = int(
            os.getenv("GATEWAY_PORT_MAX", "65535")
        )

        if not 1 <= self.port_min <= self.port_max <= 65535:
            raise ValueError(
                f"Invalid gateway port range: "
                f"{self.port_min}-{self.port_max}"
            )

        # Kubernetes Service cannot express a range as one ServicePort.
        # A range must therefore be expanded.
        self.max_service_ports = int(
            os.getenv(
                "GATEWAY_MAX_SERVICE_PORTS",
                "1024"
            )
        )

        #
        # Deployment
        #

        self.strategy = os.getenv(
            "GATEWAY_UPDATE_STRATEGY",
            "RollingUpdate"
        )

        if self.strategy not in [
            "Recreate",
            "RollingUpdate",
        ]:
            raise ValueError(
                "GATEWAY_UPDATE_STRATEGY must be "
                "Recreate or RollingUpdate"
            )

        self.rollout_timeout = int(
            os.getenv(
                "GATEWAY_ROLLOUT_TIMEOUT",
                "120"
            )
        )

        self.node_selector = json.loads(
            os.getenv(
                "GATEWAY_NODE_SELECTOR",
                "{}"
            )
        )

        self.init_privileged = (
            os.getenv(
                "GATEWAY_INIT_PRIVILEGED",
                "0"
            ) == "1"
        )

        self.core = ks.client.CoreV1Api()
        self.apps = ks.client.AppsV1Api()

        #
        # Full desired state.
        #
        # main.py sends only the affected Service after startup,
        # so the provider has to maintain the complete state itself.
        #

        self.desired = {}
        self.initialized = False

    @staticmethod
    def _config_key(pc):
        return (
            pc.proto.upper(),
            pc.namespace,
            pc.service,
            pc.port,
        )

    def patch_ports(
        self,
        new_port_configs,
        old_port_configs
    ):
        """
        Reconcile complete gateway state.

        On initial setup(), new_port_configs contains the full desired
        configuration.

        On later Service watch events it contains only the affected
        Service, therefore self.desired is used to reconstruct the
        complete state.
        """

        if not self.initialized:
            previous = {
                self._config_key(pc): pc
                for pc in old_port_configs.values()
            }

            candidate = {
                self._config_key(pc): pc
                for pc in new_port_configs.values()
            }

        else:
            previous = dict(self.desired)
            candidate = dict(self.desired)

            for pc in old_port_configs.values():
                candidate.pop(
                    self._config_key(pc),
                    None
                )

            for pc in new_port_configs.values():
                candidate[
                    self._config_key(pc)
                ] = pc

        #
        # Build the frontend representation before touching Kubernetes.
        # This also performs external-port conflict checking.
        #

        old_frontend = self._build_frontend(previous)
        new_frontend = self._build_frontend(candidate)

        nftables_conf, init_script = self._compile(
            candidate
        )

        digest = hashlib.sha256(
            (
                nftables_conf
                + "\n---INIT---\n"
                + init_script
            ).encode("utf-8")
        ).hexdigest()

        current_digest = (
            self._get_current_deployment_digest()
        )

        if current_digest != digest:
            #
            # During rollout expose only mappings that exist unchanged
            # in both revisions.
            #
            # New ports will not hit the old gateway revision.
            # Removed/changed ports are closed before replacing the
            # firewall.
            #

            stable_frontend = {
                key: value
                for key, value
                in new_frontend.items()
                if old_frontend.get(key) == value
            }

            self._ensure_gateway_services(
                stable_frontend
            )

            config_name = (
                self._ensure_versioned_configmap(
                    digest=digest,
                    nftables_conf=nftables_conf,
                    init_script=init_script
                )
            )

            self._ensure_gateway_deployment(
                config_name=config_name,
                digest=digest
            )

            self._wait_for_rollout(digest)

        #
        # The new gateway revision is ready.
        # Publish the complete desired frontend.
        #

        self._ensure_gateway_services(
            new_frontend
        )

        self.desired = candidate
        self.initialized = True

    def _parse_binding(self, pc):
        try:
            external, internal = pc.port.split(
                ":",
                1
            )
        except ValueError:
            raise ValueError(
                f"Invalid binding {pc.port!r} for "
                f"{pc.namespace}/{pc.service}"
            )

        if "-" in external:
            try:
                start_s, end_s = external.split(
                    "-",
                    1
                )

                start = int(start_s)
                end = int(end_s)

            except ValueError:
                raise ValueError(
                    f"Invalid port range "
                    f"{external!r}"
                )

            if start > end:
                raise ValueError(
                    f"Invalid descending range "
                    f"{external!r}"
                )

            #
            # Range keeps the original destination port:
            #
            # 20000-20100:
            #
            # We intentionally do not implement arbitrary range remap.
            #

            if internal != "":
                raise ValueError(
                    f"Port range {external!r} "
                    f"must have an empty internal port"
                )

            target_port = None

        else:
            try:
                start = end = int(external)
            except ValueError:
                raise ValueError(
                    f"Invalid external port "
                    f"{external!r}"
                )

            if internal:
                try:
                    target_port = int(internal)
                except ValueError:
                    raise ValueError(
                        f"Invalid internal port "
                        f"{internal!r}"
                    )

                if not 1 <= target_port <= 65535:
                    raise ValueError(
                        f"Invalid internal port "
                        f"{target_port}"
                    )

            else:
                target_port = start

        if start < 1 or end > 65535:
            raise ValueError(
                f"Port outside 1-65535: "
                f"{external}"
            )

        if (
            start < self.port_min
            or end > self.port_max
        ):
            raise ValueError(
                f"{pc.namespace}/{pc.service}: "
                f"external port {external} is outside "
                f"router-forwarded range "
                f"{self.port_min}-{self.port_max}"
            )

        proto = pc.proto.upper()

        if proto == "ANY":
            protocols = [
                "TCP",
                "UDP",
            ]

        elif proto in [
            "TCP",
            "UDP",
        ]:
            protocols = [proto]

        else:
            raise ValueError(
                f"Unsupported protocol {proto}"
            )

        return {
            "pc": pc,
            "start": start,
            "end": end,
            "external": external,
            "target_port": target_port,
            "protocols": protocols,
        }

    def _build_frontend(self, desired):
        """
        Expand desired state to individual MetalLB Service ports.

        key:
            (protocol, external_port)

        value:
            (namespace, service, target_port)

        The key must be globally unique for exposed traffic.
        """

        frontend = {}

        for pc in desired.values():
            binding = self._parse_binding(pc)

            for protocol in binding["protocols"]:
                for external_port in range(
                    binding["start"],
                    binding["end"] + 1
                ):
                    if binding["start"] == binding["end"]:
                        target_port = (
                            binding["target_port"]
                        )
                    else:
                        target_port = external_port

                    key = (
                        protocol,
                        external_port
                    )

                    value = (
                        pc.namespace,
                        pc.service,
                        target_port
                    )

                    if (
                        key in frontend
                        and frontend[key] != value
                    ):
                        old = frontend[key]

                        raise ValueError(
                            f"External "
                            f"{protocol}/{external_port} "
                            f"conflict: "
                            f"{old[0]}/{old[1]} "
                            f"and "
                            f"{pc.namespace}/{pc.service}"
                        )

                    frontend[key] = value

        if len(frontend) > self.max_service_ports:
            raise ValueError(
                f"PodGateway would create "
                f"{len(frontend)} Service ports; "
                f"limit is "
                f"{self.max_service_ports}. "
                f"Increase "
                f"GATEWAY_MAX_SERVICE_PORTS "
                f"if this is intentional."
            )

        return frontend

    def _get_service_ip(
        self,
        namespace,
        name,
        cache
    ):
        key = (
            namespace,
            name
        )

        if key in cache:
            return cache[key]

        service = (
            self.core.read_namespaced_service(
                name=name,
                namespace=namespace
            )
        )

        cluster_ip = service.spec.cluster_ip

        if (
            not cluster_ip
            or cluster_ip == "None"
        ):
            raise ValueError(
                f"{namespace}/{name} is headless "
                f"and cannot be used as a "
                f"PodGateway DNAT target"
            )

        address = ipaddress.ip_address(
            cluster_ip
        )

        if address.version != 4:
            raise ValueError(
                f"{namespace}/{name}: "
                f"IPv6 ClusterIP is currently "
                f"unsupported: {cluster_ip}"
            )

        cache[key] = cluster_ip

        return cluster_ip

    def _compile(self, desired):
        #
        # Conflict checking and range-size checking.
        #
        self._build_frontend(desired)

        service_cache = {}
        rules = []

        for pc in desired.values():
            binding = self._parse_binding(pc)

            cluster_ip = self._get_service_ip(
                pc.namespace,
                pc.service,
                service_cache
            )

            for protocol in binding["protocols"]:
                rules.append({
                    "pc": pc,
                    "protocol": protocol,
                    "start": binding["start"],
                    "end": binding["end"],
                    "target_port":
                        binding["target_port"],
                    "cluster_ip": cluster_ip,
                })

        return (
            self._build_nftables(rules),
            self._build_init_script()
        )

    def _build_nftables(self, rules):
        nat_rules = []
        forward_rules = []

        for rule in sorted(
            rules,
            key=lambda r: (
                r["protocol"],
                r["start"],
                r["end"],
                r["pc"].namespace,
                r["pc"].service,
            )
        ):
            proto = rule[
                "protocol"
            ].lower()

            ip = rule["cluster_ip"]

            if (
                rule["start"]
                != rule["end"]
            ):
                external = (
                    f'{rule["start"]}-'
                    f'{rule["end"]}'
                )

                #
                # No port remap for a range.
                #

                nat_rules.append(
                    f"        "
                    f"{proto} dport {external} "
                    f"dnat to {ip}"
                )

                forward_rules.append(
                    f"        "
                    f"ct status dnat "
                    f"ip daddr {ip} "
                    f"{proto} dport {external} "
                    f"ct state new accept"
                )

            else:
                external = rule["start"]
                internal = rule["target_port"]

                nat_rules.append(
                    f"        "
                    f"{proto} dport {external} "
                    f"dnat to {ip}:{internal}"
                )

                forward_rules.append(
                    f"        "
                    f"ct status dnat "
                    f"ip daddr {ip} "
                    f"{proto} dport {internal} "
                    f"ct state new accept"
                )

        nat_text = "\n".join(nat_rules)
        forward_text = "\n".join(
            forward_rules
        )

        return f"""flush ruleset

table ip pod_gateway_nat {{
    chain prerouting {{
        type nat hook prerouting priority dstnat;
        policy accept;

{nat_text}
    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat;
        policy accept;

        #
        # Backend replies must come back through this gateway
        # network namespace so its conntrack state can undo DNAT.
        #
        ct status dnat masquerade
    }}
}}

table inet pod_gateway_filter {{
    chain input {{
        type filter hook input priority filter;
        policy drop;

        iifname "lo" accept

        ct state invalid drop
        ct state established,related accept
    }}

    chain output {{
        type filter hook output priority filter;
        policy drop;

        oifname "lo" accept

        ct state established,related accept

        #
        # Permit locally generated routing errors required for PMTU
        # and normal IP forwarding behaviour.
        #
        ip protocol icmp icmp type {{
            destination-unreachable,
            time-exceeded,
            parameter-problem
        }} accept
    }}

    chain forward {{
        type filter hook forward priority filter;
        policy drop;

        ct state invalid drop
        ct state established,related accept

{forward_text}
    }}
}}
"""

    def _build_init_script(self):
        return """#!/bin/sh
set -eu

#
# The gateway routes packets inside its own pod network namespace.
#

sysctl -w net.ipv4.ip_forward=1

sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0
sysctl -w net.ipv4.conf.eth0.rp_filter=0

sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.default.accept_redirects=0
sysctl -w net.ipv4.conf.eth0.accept_redirects=0

sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.default.send_redirects=0
sysctl -w net.ipv4.conf.eth0.send_redirects=0

sysctl -w net.ipv4.conf.all.accept_source_route=0
sysctl -w net.ipv4.conf.default.accept_source_route=0
sysctl -w net.ipv4.conf.eth0.accept_source_route=0

#
# Validate the complete ruleset first.
#

nft --check -f /config/nftables.conf

#
# nftables applies the file transactionally.
#

nft -f /config/nftables.conf
"""

    def _configmap_name(self, digest):
        prefix = re.sub(
            r"[^a-z0-9.-]+",
            "-",
            self.gateway_config_prefix.lower()
        ).strip("-.")

        return (
            f"{prefix[:46]}-"
            f"{digest[:16]}"
        )

    def _ensure_versioned_configmap(
        self,
        digest,
        nftables_conf,
        init_script
    ):
        name = self._configmap_name(
            digest
        )

        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/name":
                        self.gateway_deployment,
                    "app.kubernetes.io/managed-by":
                        "port-configurator",
                    "pod-gateway-config": "1",
                },
            },
            "immutable": True,
            "data": {
                "nftables.conf":
                    nftables_conf,
                "init.sh":
                    init_script,
            },
        }

        try:
            self.core.create_namespaced_config_map(
                namespace=self.namespace,
                body=body
            )

        except ApiException as e:
            if e.status != 409:
                raise

        return name

    def _gateway_labels(self):
        return {
            "app.kubernetes.io/name":
                self.gateway_deployment,
            "app.kubernetes.io/component":
                "network-gateway",
        }

    def _deployment_body(
        self,
        config_name,
        digest
    ):
        labels = self._gateway_labels()

        annotations = {
            self.CONFIG_HASH_ANNOTATION:
                digest,
        }

        if self.init_privileged:
            init_security = {
                "privileged": True,
                "runAsUser": 0,
                "readOnlyRootFilesystem": True,
                "seccompProfile": {
                    "type": "RuntimeDefault",
                },
            }

        else:
            init_security = {
                "privileged": False,
                "runAsUser": 0,
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {
                    "drop": ["ALL"],
                    "add": ["NET_ADMIN"],
                },
                "seccompProfile": {
                    "type": "RuntimeDefault",
                },
            }

        if self.strategy == "RollingUpdate":
            strategy = {
                "type": "RollingUpdate",
                "rollingUpdate": {
                    "maxUnavailable": 0,
                    "maxSurge": 1,
                },
            }

        else:
            strategy = {
                "type": "Recreate",
            }

        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",

            "metadata": {
                "name":
                    self.gateway_deployment,
                "namespace":
                    self.namespace,
                "labels":
                    labels,
            },

            "spec": {
                "replicas": 1,

                "revisionHistoryLimit": 3,

                "strategy":
                    strategy,

                "selector": {
                    "matchLabels":
                        labels,
                },

                "template": {
                    "metadata": {
                        "labels":
                            labels,

                        "annotations":
                            annotations,
                    },

                    "spec": {
                        #
                        # The gateway itself gets no Kubernetes token.
                        #
                        "automountServiceAccountToken":
                            False,

                        "enableServiceLinks":
                            False,

                        "nodeSelector":
                            self.node_selector,

                        "terminationGracePeriodSeconds":
                            1,

                        "initContainers": [
                            {
                                "name":
                                    "network-init",

                                "image":
                                    self.init_image,

                                "imagePullPolicy":
                                    "IfNotPresent",

                                "command": [
                                    "/bin/sh",
                                    "/config/init.sh",
                                ],

                                "securityContext":
                                    init_security,

                                "volumeMounts": [
                                    {
                                        "name":
                                            "gateway-config",
                                        "mountPath":
                                            "/config",
                                        "readOnly":
                                            True,
                                    }
                                ],

                                "resources": {
                                    "requests": {
                                        "cpu":
                                            "5m",
                                        "memory":
                                            "8Mi",
                                    },

                                    "limits": {
                                        "cpu":
                                            "100m",
                                        "memory":
                                            "64Mi",
                                    },
                                },
                            }
                        ],

                        "containers": [
                            {
                                "name":
                                    "gateway",

                                "image":
                                    self.pause_image,

                                "imagePullPolicy":
                                    "IfNotPresent",

                                "securityContext": {
                                    "runAsUser":
                                        65534,

                                    "runAsGroup":
                                        65534,

                                    "runAsNonRoot":
                                        True,

                                    "allowPrivilegeEscalation":
                                        False,

                                    "readOnlyRootFilesystem":
                                        True,

                                    "capabilities": {
                                        "drop":
                                            ["ALL"],
                                    },

                                    "seccompProfile": {
                                        "type":
                                            "RuntimeDefault",
                                    },
                                },

                                "resources": {
                                    "requests": {
                                        "cpu":
                                            "1m",
                                        "memory":
                                            "4Mi",
                                    },

                                    "limits": {
                                        "cpu":
                                            "20m",
                                        "memory":
                                            "16Mi",
                                    },
                                },
                            }
                        ],

                        "volumes": [
                            {
                                "name":
                                    "gateway-config",

                                "configMap": {
                                    "name":
                                        config_name,

                                    "defaultMode":
                                        365,
                                },
                            }
                        ],
                    },
                },
            },
        }

    def _get_current_deployment_digest(self):
        try:
            deployment = (
                self.apps.read_namespaced_deployment(
                    name=self.gateway_deployment,
                    namespace=self.namespace
                )
            )

        except ApiException as e:
            if e.status == 404:
                return None

            raise

        annotations = (
            deployment
            .spec
            .template
            .metadata
            .annotations
            or {}
        )

        return annotations.get(
            self.CONFIG_HASH_ANNOTATION
        )

    def _ensure_gateway_deployment(
        self,
        config_name,
        digest
    ):
        body = self._deployment_body(
            config_name,
            digest
        )

        try:
            self.apps.read_namespaced_deployment(
                name=self.gateway_deployment,
                namespace=self.namespace
            )

        except ApiException as e:
            if e.status != 404:
                raise

            self.apps.create_namespaced_deployment(
                namespace=self.namespace,
                body=body
            )

            print(
                f"Created gateway Deployment "
                f"{self.namespace}/"
                f"{self.gateway_deployment} "
                f"revision {digest[:12]}"
            )

            return

        self.apps.patch_namespaced_deployment(
            name=self.gateway_deployment,
            namespace=self.namespace,
            body=body
        )

        print(
            f"Updated gateway Deployment "
            f"{self.namespace}/"
            f"{self.gateway_deployment} "
            f"revision {digest[:12]}"
        )

    def _wait_for_rollout(self, digest):
        for _ in range(
            self.rollout_timeout
        ):
            deployment = (
                self.apps.read_namespaced_deployment(
                    name=self.gateway_deployment,
                    namespace=self.namespace
                )
            )

            status = deployment.status

            observed = (
                status.observed_generation
                or 0
            )

            generation = (
                deployment.metadata.generation
                or 0
            )

            updated = (
                status.updated_replicas
                or 0
            )

            available = (
                status.available_replicas
                or 0
            )

            replicas = (
                status.replicas
                or 0
            )

            current_digest = (
                deployment
                .spec
                .template
                .metadata
                .annotations
                or {}
            ).get(
                self.CONFIG_HASH_ANNOTATION
            )

            if (
                current_digest == digest
                and observed >= generation
                and updated == 1
                and available == 1
                and replicas == 1
            ):
                return

            sleep(1)

        raise TimeoutError(
            f"Gateway Deployment rollout "
            f"did not complete within "
            f"{self.rollout_timeout}s"
        )

    def _service_name(self, protocol):
        return (
            f"{self.gateway_service_prefix}-"
            f"{protocol.lower()}"
        )

    def _metallb_annotations(self):
        annotations = {
            "metallb.io/loadBalancerIPs":
                self.load_balancer_ip,

            "metallb.io/allow-shared-ip":
                self.shared_ip_key,
        }

        if self.metallb_address_pool:
            annotations[
                "metallb.io/address-pool"
            ] = self.metallb_address_pool

        return annotations

    def _ensure_gateway_services(
        self,
        frontend
    ):
        """
        Create one LoadBalancer Service for TCP and one for UDP.

        Both request the same MetalLB IP and select the exact same
        gateway pods, so MetalLB can share the IP between them.
        """

        labels = self._gateway_labels()

        for protocol in [
            "TCP",
            "UDP",
        ]:
            service_name = (
                self._service_name(protocol)
            )

            external_ports = sorted(
                port
                for proto, port
                in frontend.keys()
                if proto == protocol
            )

            if not external_ports:
                try:
                    self.core.delete_namespaced_service(
                        name=service_name,
                        namespace=self.namespace
                    )

                except ApiException as e:
                    if e.status != 404:
                        raise

                continue

            service_ports = [
                {
                    "name":
                        f"p-{port}",

                    "protocol":
                        protocol,

                    "port":
                        port,

                    #
                    # The gateway nftables rules listen at the same
                    # external port in the pod network namespace.
                    #
                    "targetPort":
                        port,
                }

                for port in external_ports
            ]

            annotations = (
                self._metallb_annotations()
            )

            body = {
                "apiVersion": "v1",
                "kind": "Service",

                "metadata": {
                    "name":
                        service_name,

                    "namespace":
                        self.namespace,

                    "labels": {
                        "app.kubernetes.io/name":
                            self.gateway_deployment,

                        "app.kubernetes.io/component":
                            "network-gateway",

                        "app.kubernetes.io/managed-by":
                            "port-configurator",
                    },

                    "annotations":
                        annotations,
                },

                "spec": {
                    "type":
                        "LoadBalancer",

                    "allocateLoadBalancerNodePorts":
                        self.allocate_node_ports,

                    "externalTrafficPolicy":
                        self.external_traffic_policy,

                    "selector":
                        labels,

                    "ports":
                        service_ports,
                },
            }

            try:
                current = (
                    self.core
                    .read_namespaced_service(
                        name=service_name,
                        namespace=self.namespace
                    )
                )

            except ApiException as e:
                if e.status != 404:
                    raise

                self.core.create_namespaced_service(
                    namespace=self.namespace,
                    body=body
                )

                print(
                    f"Created gateway Service "
                    f"{self.namespace}/"
                    f"{service_name}"
                )

                continue

            #
            # Preserve immutable Service fields such as clusterIP,
            # but replace the managed fields.
            #

            current_annotations = (
                current.metadata.annotations
                or {}
            )

            current_annotations.update(
                annotations
            )

            #
            # Remove a stale address-pool annotation if configuration
            # no longer specifies one.
            #
            if not self.metallb_address_pool:
                current_annotations.pop(
                    "metallb.io/address-pool",
                    None
                )

            current.metadata.annotations = (
                current_annotations
            )

            current.spec.type = (
                "LoadBalancer"
            )

            current.spec.selector = labels

            current.spec.external_traffic_policy = (
                self.external_traffic_policy
            )

            current.spec.allocate_load_balancer_node_ports = (
                self.allocate_node_ports
            )

            current.spec.ports = [
                ks.client.V1ServicePort(
                    name=f"p-{port}",
                    protocol=protocol,
                    port=port,
                    target_port=port
                )
                for port in external_ports
            ]

            if (
                self.external_traffic_policy
                != "Local"
            ):
                current.spec.health_check_node_port = (
                    None
                )

            self.core.replace_namespaced_service(
                name=service_name,
                namespace=self.namespace,
                body=current
            )