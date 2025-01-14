from configs import port_provider, lock_file
from dataclasses import dataclass
import kubernetes as ks
import socket
import re

ks.config.load_incluster_config()


@dataclass(eq=True, frozen=True)
class PortConfig:
    """Port configuration for services"""
    port: str  # is pair <ingress_port>:<svc_port>
    proto: str
    namespace: str
    service: str
    ip: str = None


class PortConfigs:
    """Port configurations for services"""
    proto_port_configs: dict = dict()

    def __init__(self, proto_port_configs=None):
        self.proto_port_configs = proto_port_configs

        if self.proto_port_configs is None:
            self.proto_port_configs = dict()
            for k in port_provider.protos:
                self.proto_port_configs[k] = dict()

    def get_port_configs(self):
        res = dict()
        for k in self.proto_port_configs.keys():
            res |= self.proto_port_configs[k]
        return res

    def add_port_config(self, port_config):
        self.proto_port_configs[port_config.proto][hash(port_config)] = port_config

    def remove_ports_by_service(self, service):
        redundant_port_configs = {h: p for h, p in self.get_port_configs().items() if p.service == service}
        for h in redundant_port_configs.keys():
            self.proto_port_configs[redundant_port_configs[h].proto].pop(h)

    def get_ports_by_service(self, service):
        return {h: p for h, p in self.get_port_configs().items() if p.service == service}

    def get_ports_by_proto(self, proto):
        return [p.port.split(":")[0] for p in self.get_port_configs().values() if p.proto == proto]

    def get_ports_by_proto_exclude_service(self, proto, service):
        return [p.port.split(":")[0] for p in self.get_port_configs().values() if p.proto == proto and p.service != service]

    def add_from_pcs(self, pcs):
        for k in pcs.proto_port_configs.keys():
            self.proto_port_configs[k] |= pcs.proto_port_configs[k]

    def add_from_cm(self):
        v1 = ks.client.CoreV1Api()
        for proto in port_provider.protos:
            try:
                config_map = v1.read_namespaced_config_map(name=port_provider.config_maps_name[proto], namespace=port_provider.namespace)
                if config_map and config_map.data:
                    for key, value in config_map.data.items():
                        if port_provider.requires_ip:
                                reg_str = "([a-z0-9-]*)/([a-z0-9-]*):([0-9]*)#([0-9.]*)"
                                res = re.match(reg_str, value).groups()
                                self.add_port_config(PortConfig(f'{key}:{res[2]}', proto, res[0], res[1], ip=res[3]))
                        else:
                            reg_str = "([a-z0-9-]*)/([a-z0-9-]*):([0-9]*)"
                            res = re.match(reg_str, value).groups()
                            self.add_port_config(PortConfig(f'{key}:{res[2]}', proto, res[0], res[1]))
            except ks.client.exceptions.ApiException as e:
                pass

    def add_from_svc(self, svc):
        proto_ports = dict()
        if svc.metadata.annotations.get(port_provider.auto_annotation_key):
            for port_config in svc.spec.ports:
                proto = port_config.protocol

                if proto not in port_provider.protos:
                    if "ANY" in port_provider.protos:
                        proto = "ANY"
                    elif "ALL" in port_provider.protos:
                        proto = "ALL"

                self.add_port_from_data(f'{port_config.port}:{port_config.port}', proto, svc)
        else:
            for proto in port_provider.protos:
                proto_ports[proto] = svc.metadata.annotations.get(port_provider.annotation_keys[proto])
            if svc.metadata.annotations and any(proto_ports.values()):
                for proto in proto_ports.keys():
                    if proto_ports[proto]:
                        for port in proto_ports[proto].split(","):
                            self.add_port_from_data(port, proto, svc)

    def add_port_from_data(self, port, proto, svc):
        if port_provider.requires_ip:
            try:
                lb_ip = svc.status.load_balancer.ingress[0].ip

                if lb_ip is None:
                    raise AttributeError

                pc = PortConfig(port, proto, svc.metadata.namespace, svc.metadata.name, lb_ip)
            except AttributeError:
                try:
                    pc = PortConfig(port, proto, svc.metadata.namespace, svc.metadata.name,
                                    socket.gethostbyname(svc.status.load_balancer.ingress[0].hostname))
                except socket.gaierror:
                    pc = PortConfig(port, proto, svc.metadata.namespace, svc.metadata.name, "192.168.0.254")
                else:
                    pc = PortConfig(port, proto, svc.metadata.namespace, svc.metadata.name, "192.168.0.254")
        else:
            pc = PortConfig(port, proto, svc.metadata.namespace, svc.metadata.name)
        self.add_port_config(pc)

    def generate_config_maps(self):
        v1 = ks.client.CoreV1Api()

        for proto in port_provider.protos:
            if port_provider.requires_ip:
                config_map = ks.client.V1ConfigMap(
                    metadata=ks.client.V1ObjectMeta(name=port_provider.config_maps_name[proto]),
                    data={(ports := pc.port.split(":"))[0]: f'{pc.namespace}/{pc.service}:{ports[1]}#{pc.ip}' for pc in
                          self.proto_port_configs[proto].values()}
                )
            else:
                config_map = ks.client.V1ConfigMap(
                    metadata=ks.client.V1ObjectMeta(name=port_provider.config_maps_name[proto]),
                    data={(ports := pc.port.split(":"))[0]: f'{pc.namespace}/{pc.service}:{ports[1]}' for pc in
                          self.proto_port_configs[proto].values()}
                )

            try:
                response = v1.create_namespaced_config_map(namespace=port_provider.namespace, body=config_map)
            except ks.client.exceptions.ApiException as e:
                if e.status == 409:
                    response = v1.delete_namespaced_config_map(name=port_provider.config_maps_name[proto], namespace=port_provider.namespace)
                    response = v1.create_namespaced_config_map(namespace=port_provider.namespace, body=config_map)
                else:
                    raise e


CONFIGS = PortConfigs()
CONFIGS.add_from_cm()


def setup():
    global CONFIGS
    v1 = ks.client.CoreV1Api()

    NEW_CONFIGS = PortConfigs()

    services = v1.list_service_for_all_namespaces(label_selector=port_provider.label_selector)

    for svc in services.items:
        NEW_CONFIGS.add_from_svc(svc)

    NEW_CONFIGS.generate_config_maps()

    port_provider.patch_ports(NEW_CONFIGS.get_port_configs(), CONFIGS.get_port_configs())

    CONFIGS = NEW_CONFIGS


def fetch_service(svc):
    lock_file.lock()
    global CONFIGS
    TMP_CONFIGS = PortConfigs()
    TMP_CONFIGS.add_from_svc(svc)
    old_port_configs = CONFIGS.get_ports_by_service(svc.metadata.name)
    new_port_configs = TMP_CONFIGS.get_port_configs()
    port_provider.patch_ports(new_port_configs, old_port_configs)
    CONFIGS.remove_ports_by_service(svc.metadata.name)
    CONFIGS.add_from_pcs(TMP_CONFIGS)
    CONFIGS.generate_config_maps()
    lock_file.unlock()


def delete_service(svc):
    lock_file.lock()
    global CONFIGS
    old_port_configs = CONFIGS.get_ports_by_service(svc.metadata.name)
    new_port_configs = dict()
    port_provider.patch_ports(new_port_configs, old_port_configs)
    CONFIGS.remove_ports_by_service(svc.metadata.name)
    CONFIGS.generate_config_maps()
    lock_file.unlock()


def monitor():
    v1 = ks.client.CoreV1Api()
    w = ks.watch.Watch()
    for event in w.stream(v1.list_service_for_all_namespaces, label_selector=port_provider.label_selector):
        svc = event['object']
        event_type = event['type']

        if event_type in ['ADDED', 'MODIFIED']:
            fetch_service(svc)
        elif event_type == 'DELETED':
            delete_service(svc)


def main():
    lock_file.lock()
    setup()
    lock_file.unlock()
    monitor()


if __name__ == "__main__":
    main()