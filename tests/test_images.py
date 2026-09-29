"""A record's pictures: the featured image, the gallery, thumbnails and the
cards that show them."""
import io
from pathlib import Path

from PIL import Image

from .conftest import make, section
from .test_attachments import upload


def picture(size=(2400, 1200), fmt="JPEG", exif_rotated=False, color="red") -> bytes:
    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif_rotated:
        exif = Image.Exif()
        exif[0x0112] = 6            # the camera was turned: rotate 90 degrees on show
        exif[0x8825] = {2: (51.0, 30.0, 0.0)}      # a GPS position, which must not travel on
        im.save(out, fmt, exif=exif)
    else:
        im.save(out, fmt)
    return out.getvalue()


def attach_picture(client, h, entity_id, name="front.jpg", **kw):
    resp = upload(client, h, entity_id, picture(**kw), name, "image/jpeg")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["attachments"][0]


def feature(client, h, entity_id, name="front.jpg", status=200, data=None, ctype="image/jpeg"):
    resp = client.post(f"/api/entities/{entity_id}/image", headers=h, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data if data is not None else picture()), name, ctype)})
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def test_the_featured_image_has_its_own_place(client, h, admin):
    box = make(client, h, name="Box")
    photo = attach_picture(client, h, box["id"], "rack.jpg")
    # An attached image is a picture in the gallery, never featured by itself.
    assert client.get(f"/api/entities/{box['id']}").get_json()["entity"]["image"] is None
    got = feature(client, h, box["id"], "front.jpg")
    assert "undo" not in got                           # nothing was replaced
    image = got["entity"]["image"]
    assert image["thumb"] == f"/attachments/{image['attachment_id']}/thumb/sm"
    # It is not one of the attachments.
    listed = client.get(f"/api/entities/{box['id']}/attachments").get_json()["attachments"]
    assert [a["id"] for a in listed] == [photo["id"]]
    tab = section(client.get(f"/e/{box['id']}/sheet?tab=attachments").get_data(as_text=True), "attachments")
    assert "front.jpg" not in tab and "rack.jpg" in tab
    history = client.get(f"/e/{box['id']}/sheet?tab=history").get_data(as_text=True)
    assert "Featured image" in history and "front.jpg" in history


def test_replacing_or_removing_it_can_be_undone(client, h, admin):
    box = make(client, h, name="Box")
    first = feature(client, h, box["id"], "front.jpg")["entity"]["image"]["attachment_id"]
    got = feature(client, h, box["id"], "new.jpg")
    assert got["message"] == "Featured image replaced" and got["undo"]["body"] == {"attachment_id": first}
    second = got["entity"]["image"]["attachment_id"]
    undo = got["undo"]
    back = client.post(undo["url"], json=undo["body"], headers=h).get_json()
    assert back["entity"]["image"]["attachment_id"] == first
    assert client.get(f"/attachments/{second}/thumb/sm").status_code == 404     # the newer one went
    gone = client.post(f"/api/entities/{box['id']}/image", json={"attachment_id": None}, headers=h).get_json()
    assert gone["entity"]["image"] is None and gone["message"] == "Featured image removed"
    again = client.post(gone["undo"]["url"], json=gone["undo"]["body"], headers=h).get_json()
    assert again["entity"]["image"]["attachment_id"] == first


def test_only_an_image_of_the_record_can_be_featured(client, h, admin, viewer):
    box, other = make(client, h, name="Box"), make(client, h, name="Other")
    assert "PNG, JPEG, GIF or WebP" in feature(client, h, box["id"], "notes.txt", 400, b"hi", "text/plain")["error"]
    text = upload(client, h, box["id"]).get_json()["attachments"][0]
    theirs = attach_picture(client, h, other["id"])
    for att_id, words in ((text["id"], "PNG, JPEG"), (theirs["id"], "not stored"), (99999, "not stored"),
                          ("1", "not stored")):
        resp = client.post(f"/api/entities/{box['id']}/image", json={"attachment_id": att_id}, headers=h)
        assert resp.status_code == 400 and words in resp.get_json()["error"]
    them, th = viewer
    resp = them.post(f"/api/entities/{box['id']}/image", headers=th, content_type="multipart/form-data",
                     data={"file": (io.BytesIO(picture()), "a.jpg", "image/jpeg")})
    assert resp.status_code == 403


def test_thumbnails_are_small_upright_webp_without_metadata(app, client, h, admin):
    box = make(client, h, name="Box")
    att = attach_picture(client, h, box["id"], size=(3000, 2000), exif_rotated=True)
    got = client.get(att["thumb"])
    assert got.status_code == 200 and got.headers["Content-Type"] == "image/webp"
    im = Image.open(io.BytesIO(got.data))
    assert im.format == "WEBP" and max(im.size) == 480
    assert im.size[1] > im.size[0]                     # turned the way the camera was held
    assert not im.getexif()
    assert max(Image.open(io.BytesIO(client.get(att["large"]).data)).size) == 1600
    # Made once, then served from the data directory.
    made = list((Path(app.config["DATA_DIR"]) / "thumbs").rglob("*.webp"))
    assert len(made) == 2
    again = client.get(att["thumb"], headers={"If-None-Match": got.headers["ETag"]})
    assert again.status_code == 304


def test_thumbnails_only_of_pictures_that_can_be_read(client, h, admin):
    box = make(client, h, name="Box")
    text = upload(client, h, box["id"]).get_json()["attachments"][0]
    assert client.get(f"/attachments/{text['id']}/thumb/sm").status_code == 404
    broken = upload(client, h, box["id"], b"not really a jpeg", "broken.jpg", "image/jpeg").get_json()["attachments"][0]
    assert client.get(f"/attachments/{broken['id']}/thumb/sm").status_code == 404
    att = attach_picture(client, h, box["id"])
    assert client.get(f"/attachments/{att['id']}/thumb/huge").status_code == 404


def test_the_purge_takes_the_thumbnails_with_the_file(app, client, h, admin):
    box = make(client, h, name="Box")
    att = attach_picture(client, h, box["id"])
    client.get(att["thumb"])
    thumbs = Path(app.config["DATA_DIR"]) / "thumbs"
    assert list(thumbs.rglob("*.webp"))
    client.post(f"/api/attachments/{att['id']}/delete", headers=h)
    assert client.get(att["thumb"]).status_code == 404
    from hyprvolt.core.records import purge
    from hyprvolt.models import db
    with app.app_context():
        purge(older_than_days=0)
        db.session.commit()
    assert not list(thumbs.rglob("*.webp"))


def test_the_overview_shows_the_featured_image_and_the_gallery(client, h, admin, viewer):
    box = make(client, h, name="Box")
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    assert "Add a featured image" in html and "gallery-strip" not in html
    them, _ = viewer
    assert "data-gallery" not in them.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    front = feature(client, h, box["id"], "front.jpg")["entity"]["image"]["attachment_id"]
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    assert f'src="/attachments/{front}/thumb/lg"' in html and "Add a featured image" not in html
    assert ">Replace</label>" in html and "gallery-strip" not in html
    assert ">Replace</label>" not in them.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    back = attach_picture(client, h, box["id"], "back.jpg")
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    assert html.count("data-gallery-item") == 2 and f"/attachments/{back['id']}/thumb/sm" in html


def test_cards_show_their_featured_image(client, h, admin):
    box, bare = make(client, h, name="Box"), make(client, h, name="Bare")
    attach_picture(client, h, bare["id"])            # an attachment doesn't make a card picture
    image = feature(client, h, box["id"])["entity"]["image"]
    html = client.get("/all?view=cards").get_data(as_text=True)
    assert html.count('class="card-image"') == 1 and f'src="{image["thumb"]}"' in html
