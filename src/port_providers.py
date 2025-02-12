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