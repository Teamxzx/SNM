from typing import Literal

from pydantic import BaseModel, Field, IPvAnyAddress, model_validator


class DeviceCreate(BaseModel):
    name: str | None = None
    ip_address: IPvAnyAddress
    device_type: Literal["router", "switch"] = "switch"
    snmp_version: Literal["2c", "3"] = "2c"
    community: str | None = "public"
    username: str | None = None
    security_level: Literal["noAuthNoPriv", "authNoPriv", "authPriv"] = "authPriv"
    auth_protocol: Literal["SHA", "MD5"] = "SHA"
    auth_password: str | None = None
    priv_protocol: Literal["AES", "DES"] = "AES"
    priv_password: str | None = None

    @model_validator(mode="after")
    def validate_credentials(self):
        if self.snmp_version == "2c" and not self.community:
            raise ValueError("community is required for SNMP v2c")
        if self.snmp_version == "3" and not self.username:
            raise ValueError("username is required for SNMP v3")
        return self


class AdminStatusUpdate(BaseModel):
    admin_status: Literal[1, 2] = Field(description="1 = up, 2 = down")


class DemoTrapCreate(BaseModel):
    device_id: int = 1
    if_index: int = 1
    event_type: Literal["linkUp", "linkDown"] = "linkDown"


class TopologyEndpointCreate(BaseModel):
    """A non-SNMP endpoint, such as a VPCS host, drawn on the topology map."""
    local_device_id: int
    local_if_index: int
    endpoint_name: str = Field(min_length=1, max_length=80)
    remote_port_name: str = Field(default="eth0", min_length=1, max_length=80)
