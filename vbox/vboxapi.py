import re, subprocess
from fastapi import FastAPI, HTTPException

app = FastAPI()

# TODO: need to add multi-OS "which" to find this
VBoxManagePath = ["/usr/bin/VBoxManage"]


def _runVBoxManage(opts):
    command = VBoxManagePath + opts
    print(command)  # debug
    process = subprocess.run(command, capture_output=True)
    if process.returncode != 0:
        error_list = process.stderr.splitlines()
        print(error_list)  # debug
        # if VBoxManage usage info is included in output, skip it
        if (len(error_list) > 4) and (error_list[4] == b"Usage:"):
            error_list = error_list[749:]
        our_error = []
        for err in error_list:
            tmp_error = err.decode("ascii")
            # strip the following prefix from error lines
            if tmp_error.startswith("VBoxManage: error: "):
                our_error.append(tmp_error[19:])
            else:
                our_error.append(tmp_error)
        raise HTTPException(status_code=404, detail=our_error)
    else:
        our_output = []
        for line in process.stdout.splitlines():
            our_output.append(line.decode("ascii"))
        return our_output


@app.get("/host")
def getHostInfo():
    version = _runVBoxManage(["-v"])[0]
    info = {"version": version, "CPUs": {}}
    hostinfo = _runVBoxManage(["list", "hostinfo"])[2:]
    for line in hostinfo:
        if line.startswith("Host time"):
            info["Host time"] = line[11:]
        elif line.startswith("Processor#"):
            cpu_num = line[10]
            tmp_key, val = line.split(":")
            key = tmp_key[12:]
            if not info["CPUs"].get(cpu_num):
                info["CPUs"][cpu_num] = {}
            info["CPUs"][cpu_num][key] = val.strip()
        else:
            key, val = line.split(":")
            info[key] = val.strip()
    return info


@app.get("/host/extpacks")
def getHostExtpacks():
    extpacks = {}
    extpacks_list = _runVBoxManage(["list", "extpacks"])[1:]
    if len(extpacks_list) == 0:
        return {}
    for line in extpacks_list:
        if line.startswith("Pack no."):
            tmp_key, val = line.split(":")
            key = tmp_key[8:].strip()
            extpacks[key] = {"Name": val.strip()}
            current_pack = key
        else:
            key, val = line.split(":")
            extpacks[current_pack][key] = val.strip()
    return extpacks


@app.get("/host/ostypes")
def getHostOstypes():
    ostypes = {}
    ostypes_list = _runVBoxManage(["list", "ostypes"])
    for line in ostypes_list:
        if len(line) == 0:
            continue
        if line.startswith("ID"):
            current_ostype = line[3:].strip()
            ostypes[current_ostype] = {}
        else:
            key, val = line.split(":")
            ostypes[current_ostype][key] = val.strip()
    return ostypes


@app.get("/host/properties")
def getHostProperties():
    properties = {}
    properties_list = _runVBoxManage(["list", "systemproperties"])
    for line in properties_list:
        key, val = line.split(":")
        properties[key] = val.strip()
    return properties


@app.get("/machines")
def getMachinesList():
    all_vms = {}
    running_vms = []
    all_list = _runVBoxManage(["list", "vms"])
    running_list = _runVBoxManage(["list", "runningvms"])
    for line in running_list:
        uuid_start = line.find("{") + 1
        running_vms.append(line[uuid_start:-1])
    for line in all_list:
        tmp_name, tmp_uuid = line.split('" {')
        name = tmp_name[1:]
        uuid = tmp_uuid[:-1]
        all_vms[name] = {"uuid": uuid, "running": "false"}
        if uuid in running_vms:
            all_vms[name]["running"] = "true"
    return all_vms


def _buildVRDE(keys):
    vrde = {"properties": {}}
    for tmp_key, val in keys.items():
        if tmp_key == "vrde":
            if val == "off":
                return {"enabled": "false"}
            else:
                vrde["enabled"] = "true"
        elif tmp_key.startswith("vrdeproperty"):
            prop_key = tmp_key[13:-1]
            key, subkey = prop_key.split("/")
            if not vrde["properties"].get(key):
                vrde["properties"][key] = {}
            vrde["properties"][key][subkey] = val.strip("<>")
        else:
            key = tmp_key[4:]
            vrde[key] = val
    return vrde


def _buildSharedFolders(vm: str):
    # --machinereadable output does not include readonly and auto-mount details, so we must get
    shares_detail = _runVBoxManage(["showvminfo", vm])
    details = {}
    processing = False
    for line in shares_detail:
        if processing:
            # share detail lines look like:
            # Name: 'share1', Host path: '/srv/testshare1' (machine mapping), writable
            # Name: 'share2', Host path: '/srv/testshare2' (machine mapping), readonly, auto-mount
            # Name: 'share3', Host path: '/srv/testshare3' (machine mapping), writable, mount-point: '/media'
            # Name: 'share4', Host path: '/srv/testshare4' (machine mapping), readonly, auto-mount, mount-point: '/mnt'
            if line.startswith("Name: "):
                split = line.split(",")
                begin = split[0].find("'") + 1
                key = split[0][begin:-1]
                details[key] = {}
                path_match = re.match(
                    " Host path\: '(.+)' \(machine mapping\)", split[1]
                )
                details[key]["Path"] = path_match.group(1)
                if split[2] == " readonly":
                    details[key]["Readonly"] = "true"
                else:
                    details[key]["Readonly"] = "false"

                if len(split) > 3:
                    if "point" in split[-1]:
                        index = split[-1].find("'") + 1
                        details[key]["Mountpoint"] = split[-1][index:-1]
                        if len(split) == 5:
                            details[key]["Automount"] = "true"
                        else:
                            details[key]["Automount"] = "false"
                    else:
                        details[key]["Mountpoint"] = "none"
                        details[key]["Automount"] = "true"
                else:
                    details[key]["Mountpoint"] = "none"
                    details[key]["Automount"] = "false"
        else:
            if line.startswith("Shared folders:"):
                # skip all other lines until we get to the shares towards the end
                processing = True
    return details


@app.get("/machines/{vm}")
def getMachinesNodeInfo(vm: str):
    nickeys = [
        "bridge",
        "cable",
        "generic",
        "hostonly",
        "intnet",
        "mac",
        "mtu",
        "nat",
        "nic",
        "sock",
        "tcp",
        "tracing",
    ]

    nodeinfo = {}
    vrde_list = {}
    found_shares = False
    nodeinfo_list = _runVBoxManage(["showvminfo", vm, "--machinereadable"])
    for line in nodeinfo_list:
        delim = line.find("=")
        key = line[:delim].strip('"=')
        val = line[delim:].strip('"=')
        # if line contains a network type key, skip
        if list(filter(key.startswith, nickeys)) != []:
            continue
        if key.lower().startswith("vrde"):
            vrde_list[key] = val
        elif key.startswith("SharedFolder"):
            found_shares = True
        elif key.startswith("captureopts"):
            nodeinfo["captureopts"] = {}
            if key.strip():
                for opt in val.split(","):
                    opt_key, opt_val = opt.split("=")
                    nodeinfo["captureopts"][opt_key] = opt_val
        else:
            nodeinfo[key] = val
    nodeinfo["vrde"] = _buildVRDE(vrde_list)
    if found_shares:
        nodeinfo["shares"] = _buildSharedFolders(vm)
    nodeinfo["nics"] = getNicInfo(vm)
    return nodeinfo


@app.get("/dhcpservers")
def getDhcpserversList():
    dhcpserv = {}
    dhcpserv_list = _runVBoxManage(["list", "dhcpservers"])
    for line in dhcpserv_list:
        if len(line) == 0:
            continue
        if line.startswith("NetworkName"):
            globalopts = False
            key, val = line.split(": ")
            current_dhcp = val.strip()
            dhcpserv[current_dhcp] = {}
        elif globalopts:
            key, val = line.split(":")
            dhcpserv[current_dhcp]["Global opts"][key.strip()] = val.strip()
        elif line.startswith("Global options"):
            dhcpserv[current_dhcp]["Global opts"] = {}
            globalopts = True
        else:
            key, val = line.split(": ")
            dhcpserv[current_dhcp][key] = val.strip()
    return dhcpserv


@app.get("/hostonlynets")
def getHostonlynetsList():
    hostonly = {}
    hostonly_list = _runVBoxManage(["list", "hostonlyifs"])
    for line in hostonly_list:
        if len(line) == 0:
            continue
        if line.startswith("Name:"):
            current_hostonly = line[5:].strip()
            hostonly[current_hostonly] = {}
        else:
            key, val = line.split(": ")
            hostonly[current_hostonly][key] = val.strip()
    return hostonly


@app.get("/intnets")
def getInternalnetsList():
    intnets = []
    intnets_list = _runVBoxManage(["list", "intnets"])
    for line in intnets_list:
        key, val = line.split(":")
        intnets.append(val.strip())
    return intnets


@app.get("/natnetworks")
def getNatnetworksList():
    natnets = {}
    natnets_list = _runVBoxManage(["list", "natnets"])
    for line in natnets_list:
        if len(line) == 0:
            continue
        if line.startswith("NetworkName"):
            loopmap, forward_ipv4, forward_ipv6 = False, False, False
            key, val = line.split(": ")
            current_net = val.strip()
            natnets[current_net] = {}
        elif line.startswith("loopback mappings"):
            natnets[current_net]["loopback mappings"] = {}
            loopmap, forward_ipv4, forward_ipv6 = True, False, False
        elif line.startswith("Port-forwarding"):
            if not natnets[current_net].get("Port forwarding"):
                natnets[current_net]["Port forwarding"] = {}
            if line.endswith("(ipv4)"):
                loopmap, forward_ipv4, forward_ipv6 = False, True, False
                natnets[current_net]["Port forwarding"]["ipv4"] = {}
            elif line.endswith("(ipv6)"):
                loopmap, forward_ipv4, forward_ipv6 = False, False, True
                natnets[current_net]["Port forwarding"]["ipv6"] = {}
        elif forward_ipv4:
            delim = line.find(":")
            key = line[:delim].strip()
            val = line[delim + 1 :].strip()
            natnets[current_net]["Port forwarding"]["ipv4"][key] = val
        elif forward_ipv6:
            delim = line.find(":")
            key = line[:delim].strip()
            val = line[delim + 1 :].strip()
            natnets[current_net]["Port forwarding"]["ipv6"][key] = val
        elif loopmap:
            key, val = line.split("=")
            natnets[current_net]["loopback mappings"][key.strip()] = val.strip()
        else:
            key, val = line.split(": ")
            natnets[current_net][key] = val.strip()
    return natnets


def getNicInfo(vm: str):
    nicinfo = {}
    nicinfo_list = _runVBoxManage(["showvminfo", vm])
    for line in nicinfo_list:
        if line.startswith("NIC"):
            delim = line.find(":") + 1
            nic_num = line[4]
            if "Generic" in line:
                line = line.replace("', ", "@")
                line = line.replace(" }", "")
            if "Settings" in line[5:delim]:
                line = line.replace(", receive:", "/ receive=")
                line = line.replace("(send:", ":send=")
            else:
                nicinfo[nic_num] = {}
                if "disabled" in line[delim:]:
                    nicinfo[nic_num] = "disabled"
                    continue
            nic_settings = line[delim:].split(",")
            for setting in nic_settings:
                if "Trace" in setting:
                    trace_delim = setting.find("(")
                    trace_val = setting[setting.find(":") + 1 : trace_delim]
                    trace_file = setting[setting.find("file: ") + 6 : -1]
                    nicinfo[nic_num]["Trace"] = trace_val.strip()
                    nicinfo[nic_num]["Trace file"] = trace_file.strip()
                    continue
                tmp_key, tmp_val = setting.split(":")
                key = tmp_key.strip()
                if key == "Attachment":
                    if "NAT Network" in tmp_val:
                        delim = tmp_val.find("'") + 1
                        nicinfo[nic_num]["network"] = tmp_val[delim:-1]
                        val = "natnetwork"
                    elif "NAT" in tmp_val:
                        val = "nat"
                    elif "Bridged" in tmp_val:
                        delim = tmp_val.find("'") + 1
                        nicinfo[nic_num]["interface"] = tmp_val[delim:-1]
                        val = "bridged"
                    elif "Internal" in tmp_val:
                        delim = tmp_val.find("'") + 1
                        nicinfo[nic_num]["network"] = tmp_val[delim:-1]
                        val = "intnet"
                    elif "Host-only" in tmp_val:
                        delim = tmp_val.find("'") + 1
                        nicinfo[nic_num]["network"] = tmp_val[delim:-1]
                        val = "hostonly"
                    elif "Generic" in tmp_val:
                        tmp_drv, tmp_prop = tmp_val.split("{ ")
                        delim = tmp_drv.find("'") + 1
                        nicinfo[nic_num]["generic driver"] = tmp_drv[delim:].strip("' ")
                        nicinfo[nic_num]["generic properties"] = {}
                        val = "generic"
                        if tmp_prop:
                            for prop in tmp_prop.split("@"):
                                prop_key, prop_val = prop.split("=")
                                nicinfo[nic_num]["generic properties"][
                                    prop_key
                                ] = prop_val.strip("'")
                elif key in ["Socket", "TCP Window"]:
                    val = {}
                    tmp_send, tmp_recv = tmp_val.split("/")
                    val["send"] = tmp_send[tmp_send.find("=") :].strip("= )")
                    val["receive"] = tmp_recv[tmp_recv.find("=") :].strip("= )")
                else:
                    val = tmp_val.strip(" )")
                nicinfo[nic_num][key] = val
    return nicinfo
