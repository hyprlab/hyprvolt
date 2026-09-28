"""A record's pictures: the main image, the gallery, thumbnails and the
cards that show them."""
import io
from pathlib import Path

from PIL import Image

from .conftest import make
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


def test_the_first_picture_is_the_main_image_until_another_is_chosen(client, h, admin):
    box = make(client, h, name="Box")
    assert client.get(f"/api/entities/{box['id']}").get_json()["entity"]["image"] is None
    upload(client, h, box["id"])                      # a text file is never a picture
    front = attach_picture(client, h, box["id"], "front.jpg")
    back = attach_picture(client, h, box["id"], "back.jpg")
    assert front["thumb"] == f"/attachments/{front['id']}/thumb/sm"
    image = client.get(f"/api/entities/{box['id']}").get_json()["entity"]["image"]
    assert image["attachment_id"] == front["id"]

    resp = client.post(f"/api/entities/{box['id']}/image", json={"attachment_id": back["id"]}, headers=h)
    assert resp.get_json()["entity"]["image"]["attachment_id"] == back["id"]
    history = client.get(f"/e/{box['id']}/sheet?tab=history").get_data(as_text=True)
    assert "Main image" in history and "back.jpg" in history

    # Removing the main image leaves the first one in its place; Undo brings it back.
    undo = client.post(f"/api/attachments/{back['id']}/delete", headers=h).get_json()["undo"]
    assert client.get(f"/api/entities/{box['id']}").get_json()["entity"]["image"]["attachment_id"] == front["id"]
    client.post(undo["url"], json=undo["body"], headers=h)
    assert client.get(f"/api/entities/{box['id']}").get_json()["entity"]["image"]["attachment_id"] == back["id"]


def test_only_a_picture_of_the_record_can_be_its_main_image(client, h, admin, viewer):
    box, other = make(client, h, name="Box"), make(client, h, name="Other")
    text = upload(client, h, box["id"]).get_json()["attachments"][0]
    theirs = attach_picture(client, h, other["id"])
    for att_id in (text["id"], theirs["id"], 99999, "1"):
        resp = client.post(f"/api/entities/{box['id']}/image", json={"attachment_id": att_id}, headers=h)
        assert resp.status_code == 400 and resp.get_json()["error"]
    mine = attach_picture(client, h, box["id"])
    them, th = viewer
    resp = them.post(f"/api/entities/{box['id']}/image", json={"attachment_id": mine["id"]}, headers=th)
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


def test_the_overview_shows_the_main_image_and_the_gallery(client, h, admin):
    box = make(client, h, name="Box")
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    assert "data-gallery" not in html
    front = attach_picture(client, h, box["id"], "front.jpg")
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    assert f'src="/attachments/{front["id"]}/thumb/lg"' in html and "gallery-strip" not in html
    back = attach_picture(client, h, box["id"], "back.jpg")
    client.post(f"/api/entities/{box['id']}/image", json={"attachment_id": back["id"]}, headers=h)
    html = client.get(f"/e/{box['id']}/sheet").get_data(as_text=True)
    main = html.index('class="gallery-main"')
    assert html.index(f"/attachments/{back['id']}/thumb/lg", main) < html.index("gallery-strip")
    assert html.count("data-gallery-item") == 3        # the main image, then both in the strip
    tab = client.get(f"/e/{box['id']}/sheet?tab=attachments").get_data(as_text=True)
    assert tab.count('aria-pressed="true"') == 1 and tab.count("starbtn") == 2


def test_cards_show_their_main_image(client, h, admin):
    box, bare = make(client, h, name="Box"), make(client, h, name="Bare")
    att = attach_picture(client, h, box["id"])
    html = client.get("/all?view=cards").get_data(as_text=True)
    assert html.count('class="card-image"') == 1
    assert f'src="/attachments/{att["id"]}/thumb/sm"' in html
