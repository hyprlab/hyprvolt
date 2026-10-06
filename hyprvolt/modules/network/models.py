"""Network's tables: one detail table for its six types (a column each type
uses or leaves empty), and three of its own for what is too many to be
records: the ports on devices, the cables between them, and DNS records;
and which devices have their ports recorded one by one."""
from hyprvolt.core.models import Entity, EntityDetail
from hyprvolt.models import db, utcnow


class NetworkDetail(EntityDetail, db.Model):
    __tablename__ = "network_details"

    kind = db.Column(db.String(10))            # networks: lan, wan, vpn, other
    circuit_id = db.Column(db.String(120))     # internet connections: the ISP's name for the line
    public_ips = db.Column(db.String(300))
    bandwidth = db.Column(db.String(120))      # before download and upload: moved to them, or the notes
    download = db.Column(db.Integer)           # internet connections: megabits per second
    upload = db.Column(db.Integer)
    static_ip = db.Column(db.Boolean)          # internet connections: a fixed address, its cidr and gateway
    netmask = db.Column(db.String(45))         # before a static line's Subnet (cidr): moved to it

    network = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    vid = db.Column(db.Integer)                # VLANs: 1 to 4094
    vlan = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    cidr = db.Column(db.String(50))            # subnets: 10.0.20.0/24; a static line's: 203.0.113.24/29
    gateway = db.Column(db.String(45))
    dns_servers = db.Column(db.String(300))
    dhcp_range = db.Column(db.String(100))     # 10.0.30.100-10.0.30.199
    address = db.Column(db.String(45), index=True)   # IP addresses
    assigned = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    mac = db.Column(db.String(17))
    registrar = db.Column(db.String(120))      # domains
    dns_provider = db.Column(db.String(120))
    expires = db.Column(db.Date, index=True)
    auto_renew = db.Column(db.Boolean)
    nameservers = db.Column(db.Text)
    security = db.Column(db.String(12))        # wireless networks: wpa3, wpa2_wpa3, wpa2, enterprise, open
    bands = db.Column(db.String(10))           # 2.4, 5, 6, or two or three of them: 2.4_5
    hidden_ssid = db.Column(db.Boolean)
    subnet = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)


PORT_KINDS = (("rj45", "RJ45"), ("sfp", "SFP"), ("sfp_plus", "SFP+"), ("sfp28", "SFP28"), ("qsfp", "QSFP+"),
              ("wifi", "Wireless"), ("console", "Console"), ("other", "Other"))
SPEEDS = ((100, "100 Mb"), (1000, "1 GbE"), (2500, "2.5 GbE"), (5000, "5 GbE"), (10000, "10 GbE"),
          (25000, "25 GbE"), (40000, "40 GbE"), (100000, "100 GbE"))


class PortsRecorded(db.Model):
    """A device whose ports are recorded one by one. Any other device is
    cabled as a whole: each of its cables ends at a port with no name,
    made with the cable and removed with it."""
    __tablename__ = "network_ports_recorded"

    device_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)


class Port(db.Model):
    """A port on a device. A patch panel's front and rear ports are paired
    (``pair_id``): a trace goes in at one and out at the other. A port with
    no name is where a cable meets a device as a whole."""
    __tablename__ = "network_ports"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    kind = db.Column(db.String(10), nullable=False, default="rj45")
    speed_mbps = db.Column(db.Integer)
    poe = db.Column(db.Boolean, nullable=False, default=False)
    mac = db.Column(db.String(17), nullable=False, default="")
    vlan_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"))
    tagged = db.Column(db.String(200), nullable=False, default="")   # VLAN numbers: "20, 30"
    description = db.Column(db.String(200), nullable=False, default="")
    pair_id = db.Column(db.Integer, db.ForeignKey("network_ports.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    device = db.relationship(Entity, foreign_keys=[device_id])
    vlan = db.relationship(Entity, foreign_keys=[vlan_id])
    pair = db.relationship("Port", remote_side=[id], foreign_keys=[pair_id], post_update=True)

    @property
    def label(self) -> str:
        return f"{self.device.name} {self.name}".strip()


class Cable(db.Model):
    """A cable between two ports. Each port takes one cable."""
    __tablename__ = "network_cables"

    id = db.Column(db.Integer, primary_key=True)
    a_id = db.Column(db.Integer, db.ForeignKey("network_ports.id", ondelete="CASCADE"), nullable=False, unique=True)
    b_id = db.Column(db.Integer, db.ForeignKey("network_ports.id", ondelete="CASCADE"), nullable=False, unique=True)
    label = db.Column(db.String(60), nullable=False, default="")
    color = db.Column(db.String(30), nullable=False, default="")
    length_m = db.Column(db.Float)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    a = db.relationship(Port, foreign_keys=[a_id])
    b = db.relationship(Port, foreign_keys=[b_id])

    def other(self, port: Port) -> Port:
        return self.b if port.id == self.a_id else self.a

    @property
    def text(self) -> str:
        bits = [self.label, self.color, f"{self.length_m:g} m" if self.length_m else ""]
        return ", ".join(b for b in bits if b)


DNS_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS", "CAA", "PTR")


class DnsRecord(db.Model):
    """A DNS record as written down by hand, not read from a server."""
    __tablename__ = "network_dns_records"

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(253), nullable=False, default="@")
    type = db.Column(db.String(6), nullable=False)
    value = db.Column(db.String(1000), nullable=False)
    ttl = db.Column(db.Integer)
    priority = db.Column(db.Integer)
    note = db.Column(db.String(200), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    domain = db.relationship(Entity, foreign_keys=[domain_id])

    @property
    def fqdn(self) -> str:
        zone = self.domain.name
        return zone if self.name in ("@", "") else f"{self.name}.{zone}"
