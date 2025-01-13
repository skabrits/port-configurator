from configs import port_provider
from main import CONFIGS
from flask import Flask, jsonify, request
import socket
import http

app = Flask(__name__)


@app.route("/validate", methods=["POST"])
def validate():
    allowed = True
    reason = "Service passed validation."

    try:
        svc = request.json["request"]["object"]
        ports_annotations = svc["metadata"]["annotations"]

        if port_provider.requires_ip:
            try:
                if svc["spec"]["type"] != "LoadBalancer":
                    allowed = False
                    reason = "Service must be of type LoadBalancer."
            except KeyError:
                allowed = False
                reason = "No type provided for service."

        if port_provider.auto_annotation_key in ports_annotations.keys():
            for port_config in svc["spec"]["ports"]:
                proto = port_config["protocol"]
                port = port_config["port"]
                external_ports = CONFIGS.get_ports_by_proto(proto)
                for ep in external_ports:
                    if is_range(ep):
                        if in_range(port, ep):
                            allowed = False
                            reason = "Port %s intersects range %s." % (port, ep)
                    else:
                        if int(ep) == int(port):
                            allowed = False
                            reason = "Port %s intersects with port %s." % (port, ep)
        else:
            for proto in port_provider.protos:
                ports = ports_annotations[port_provider.annotation_keys[proto]]
                external_ports = CONFIGS.get_ports_by_proto(proto)
                for port_binding in ports.split(","):
                    port = port_binding.split(":")[0]

                    if is_range(port):
                        if not port_provider.allows_port_range:
                            allowed = False
                            reason = "Selected provider does not allow using port ranges."
                        elif not is_valid_range(port):
                            allowed = False
                            reason = "Range %s is incorrect - first value must be less than second." % port
                        else:
                            for ep in external_ports:
                                if is_range(ep):
                                    if intersect(ep, port):
                                        allowed = False
                                        reason = "Range %s intersects with range %s." % (port, ep)
                                else:
                                    if in_range(ep, port):
                                        allowed = False
                                        reason = "Range %s intersects with port %s." % (port, ep)
                    else:
                        if not is_valid_port(port):
                            allowed = False
                            reason = "Port %s is incorrect - must be integer." % port
                        else:
                            for ep in external_ports:
                                if is_range(ep):
                                    if in_range(port, ep):
                                        allowed = False
                                        reason = "Port %s intersects range %s." % (port, ep)
                                else:
                                    if int(ep) == int(port):
                                        allowed = False
                                        reason = "Port %s intersects with port %s." % (port, ep)
    except KeyError as e:
        allowed = False
        reason = "Object missing key, which produces error %s." % e
    except Exception as e:
        allowed = False
        reason = "Object has invalid properties, which produces error %s." % e

    return jsonify(
        {
            "response": {
                "allowed": allowed,
                "uid": request.json["request"]["uid"],
                "status": {"message": reason},
            }
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return "", http.HTTPStatus.NO_CONTENT


def is_range(port):
    return "-" in port


def parse_range(port_range):
    return int(port_range.split("-")[0]), int(port_range.split("-")[1])


def is_valid_range(port_range):
    try:
        p_0, p_1 = parse_range(port_range)
        return p_0 < p_1
    except ValueError:
        return False


def is_valid_port(port):
    try:
        int(port)
        return True
    except ValueError:
        return False


def intersect(port_range_1, port_range_2):
    p_1_0, p_1_1 = parse_range(port_range_1)
    p_2_0, p_2_1 = parse_range(port_range_2)
    return p_2_0 <= p_1_0 <= p_2_1 or p_2_0 <= p_1_1 <= p_2_1


def in_range(port, port_range):
    p = int(port)
    p_0, p_1 = parse_range(port_range)
    return p_0 <= p <= p_1
