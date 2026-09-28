"""The demo homelab's places: a house with a basement rack and an office.
The rack holds the passive parts as labels; Hardware's demo puts the
equipment in it as records."""
from hyprvolt.models import db

from .models import RackMount


def seed(demo):
    home = demo.add("site", "Home lab", key="home", tags=["lab"], code="HOME", address="12 Birch Lane",
                    city="Springfield", region="IL", postal_code="62704", country="United States")
    house = demo.add("building", "House", key="house", location=home, code="H")
    basement = demo.add("room", "Basement", key="basement", location=house, floor="-1", code="BSMT",
                        notes="Cool and dry. The rack stands by the north wall, next to the electrical panel.")
    demo.add("room", "Office", key="office", location=house, floor="1", code="OFC")
    rack = demo.add("rack", "Rack 1", key="rack-1", location=basement, tags=["lab"], height_u=24,
                    numbering="bottom", depth_mm=600,
                    notes="24U open frame. Power comes from the UPS at the bottom; the PDU is on the rear.")
    shelf = demo.add("shelf", "Rack shelf", key="rack-shelf", location=rack, height_u=2,
                     notes="Holds the mini PCs and the modem.")
    demo.add("shelf", "Storage shelf", key="storage-shelf", location=basement,
             notes="Spare drives, cables and the old router.")
    demo.add("site", "Offsite backup", key="offsite", status="planned", code="OFF",
             notes="A NAS at a friend's place for offsite copies. Not set up yet.")

    def mount(label, position, height, face="front", entity=None):
        db.session.add(RackMount(rack_id=rack.id, entity_id=entity.id if entity else None,
                                 label="" if entity else label, position_u=position, height_u=height, face=face))

    mount("Cable manager", 23, 1)
    mount("Blanking plate", 19, 1)
    mount(None, 9, 2, "full", entity=shelf)
