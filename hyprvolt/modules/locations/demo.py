"""The demo homelab's places: a house with a basement rack and an office
closet. The equipment is in the rack as labels until a module documents it
as records of its own."""
from hyprvolt.models import db

from .models import RackMount


def seed(demo):
    home = demo.add("site", "Home lab", key="home", tags=["lab"], code="HOME", address="12 Birch Lane, Springfield")
    house = demo.add("building", "House", key="house", location=home, code="H")
    basement = demo.add("room", "Basement", key="basement", location=house, floor="-1", code="BSMT",
                        notes="Cool and dry. The rack stands by the north wall, next to the electrical panel.")
    demo.add("room", "Office", key="office", location=house, floor="1", code="OFC")
    rack = demo.add("rack", "Rack 1", key="rack-1", location=basement, tags=["lab"], height_u=24,
                    numbering="bottom", depth_mm=600,
                    notes="24U open frame. Power comes from the UPS at the bottom; the PDU runs up the rear.")
    shelf = demo.add("shelf", "Rack shelf", key="rack-shelf", location=rack, height_u=2,
                     notes="Holds the mini PCs and the modem.")
    demo.add("shelf", "Storage shelf", key="storage-shelf", location=basement,
             notes="Spare drives, cables and the old router.")
    demo.add("site", "Offsite backup", key="offsite", status="planned", code="OFF",
             notes="A NAS at a friend's place for offsite copies. Not set up yet.")

    def mount(label, position, height, face="front", entity=None):
        db.session.add(RackMount(rack_id=rack.id, entity_id=entity.id if entity else None,
                                 label="" if entity else label, position_u=position, height_u=height, face=face))

    mount("Patch panel, 24 ports", 24, 1)
    mount("Cable manager", 23, 1)
    mount("Switch sw-core", 22, 1)
    mount("Firewall edge-fw", 20, 1)
    mount("Hypervisor pve1", 16, 2, "full")
    mount("NAS nas1", 12, 2, "full")
    mount(None, 9, 2, "full", entity=shelf)
    mount("PDU", 5, 1, "rear")
    mount("UPS", 1, 3, "full")
