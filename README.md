# Port-Configurator

This project aims to provide application that manages services' port-forwarding
trough annotations.

## Supported providers
| Provider            | Protocols |   Class    |  Default BASE_NAME  | Notes                                                                                      |
|:--------------------|:---------:|:----------:|:-------------------:|:-------------------------------------------------------------------------------------------|
| Ingress-Nginx       | TCP, UDP  |   Nginx    | ingress-nginx-ports | port-forwarding includes managing configmaps, deployment's and service's ports for ingress |
| TP-link Archer C80  |    ANY    |   Router   |    tplink-ports     | port-forwarding is done via web interface (Selenium)                                       |
| MetalLB Pod Gateway |    ANY    | PodGateway |      pod-ports      | Creates a MetalLB frontend and an isolated nftables gateway pod                            |

---
**NOTE**

ANY protocol means that ports are forwarded **both** for TCP and UDP (provider supports forwarding all protocols at once).
It does not imply supporting TCP and UDP protocols separate.

---

## Consepts

Services that requre port-forwarding are found by label
set with environment variable `LABEL_SELECTOR`. Default value is `ingress-nginx-ports=1`, what corresponds to label
```yaml
ingress-nginx-ports: "1"
```

For the sake of simplicity, when managing several deployments in cluster, label key can be set separately with environment variable `BASE_NAME`. 

Annotations are used to infer ports to forward.
Annotations number equals to the number of protocols which provider supports:
each protocol has its own annotation for port forwarding.
Annotations are configured via environment variables following pattern `<PROTOCOL>_ANNOTATION_KEY`.
Default value is `<BASE_NAME>.<PROTOCOL.to_lower()>-ports`, for instance, for Nginx provider default annotations are
```bash
TCP_ANNOTATION_KEY=ingress-nginx-ports.tcp-ports
UDP_ANNOTATION_KEY=ingress-nginx-ports.udp-ports
```

Annotations must contain a string of port bindings in docker format, separated by commas:
`<external_port_1>:<internal_port_1>,<external_port_2>:<internal_port_2>`. If provider supports port ranges,
set it in format `<start_port>-<end_port>:`. A service, following preceding convention might look like:
```yaml
label:
  ingress-nginx-ports: "1"
annotations:
  ingress-nginx-ports.tcp-ports: "2222:22,1000-1010:,8080:80"
  ingress-nginx-ports.udp-ports: "53:53"
```

To forward all service's ports according to their protocols use annotation configured with environment variable `AUTO_ANNOTATION_KEY`,
which default key is `<BASE_NAME>.auto` and value `"1"`:
```yaml
ingress-nginx-ports.auto: "1"
```

## MetalLB Pod Gateway

`PodGateway` provides an L3/L4 gateway for bare-metal Kubernetes clusters using MetalLB.

Instead of configuring one physical-router forwarding rule for every Kubernetes Service, the physical router forwards one large static TCP/UDP port range to a single MetalLB address.

Example:

```text
Internet
    |
    v
TP-Link Archer C80
20000-60000 TCP+UDP
    |
    v
192.168.0.254
MetalLB LoadBalancer IP
    |
    +-- pod-gateway-tcp
    |
    +-- pod-gateway-udp
            |
            v
       gateway pod
       nftables DNAT
            |
            v
       ClusterIP Services
```

The gateway pod does not run a network server.

Its init container receives `NET_ADMIN`, configures IP forwarding and installs an nftables ruleset, then exits. The main container runs without Linux capabilities and without a Kubernetes ServiceAccount token.

The gateway firewall is default-deny. Only mappings explicitly configured through Service annotations are forwarded.

### Requirements

- Kubernetes 1.24 or newer is recommended.
- MetalLB must already be installed and configured.
- The configured gateway address must belong to a MetalLB `IPAddressPool`.
- The physical router must forward the configured external port range to the MetalLB gateway IP.

For example, configure the physical router with one rule:

```text
20000-60000 TCP+UDP -> 192.168.0.254
```

### Example MetalLB configuration

If the gateway has a dedicated address:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: gateway
  namespace: metallb-system
spec:
  addresses:
    - 192.168.0.254/32
  autoAssign: false

---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: gateway
  namespace: metallb-system
spec:
  ipAddressPools:
    - gateway
```

An existing MetalLB address pool may be used instead.

### Provider configuration

Example environment:

```yaml
PORT_PROVIDER: PodGateway
PORT_PROVIDER_NAMESPACE: port-gateway

BASE_NAME: pod-ports

GATEWAY_LOAD_BALANCER_IP: 192.168.0.254
GATEWAY_METALLB_ADDRESS_POOL: gateway

GATEWAY_PORT_MIN: "20000"
GATEWAY_PORT_MAX: "60000"

GATEWAY_UPDATE_STRATEGY: RollingUpdate
GATEWAY_ROLLOUT_TIMEOUT: "120"

GATEWAY_EXTERNAL_TRAFFIC_POLICY: Local
GATEWAY_ALLOCATE_NODE_PORTS: "0"

GATEWAY_INIT_IMAGE: skabrits/port-gateway-init:0.1.0
GATEWAY_PAUSE_IMAGE: registry.k8s.io/pause:3.10
```

`GATEWAY_METALLB_ADDRESS_POOL` is optional when the requested IP is already unambiguously available from an existing MetalLB pool.