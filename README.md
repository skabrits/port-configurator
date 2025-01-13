# Port-Configurator

This project aims to provide application that manages services' port-forwarding
trough annotations.

## Supported providers
| Provider            | Protocols |  Class   |  Default BASE_NAME  | Notes                                                                                      |
|:--------------------|:---------:|:--------:|:-------------------:|:-------------------------------------------------------------------------------------------|
| Ingress-Nginx       | TCP, UDP  |  Nginx   | ingress-nginx-ports | port-forwarding includes managing configmaps, deployment's and service's ports for ingress |
| TP-link Archer C80  |    ANY    |  Router  |    tplink-ports     | port-forwarding is done via web interface (Selenium)                                       |

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