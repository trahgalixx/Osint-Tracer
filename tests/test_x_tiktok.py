"""Uji parser & kolektor X/TikTok dengan respons tiruan (tanpa jaringan). Jalankan: python -m tests.test_x_tiktok"""
import json
import os
import tempfile

from tracer import x_tiktok as XT
from tracer.analyze import analyze
from tracer.collectors import import_file


class R:
    def __init__(self, js):
        self._js, self.ok, self.status_code, self.headers, self.text = js, True, 200, {}, ""

    def json(self):
        return self._js


X_PAGE1 = {
    "data": [
        {"id": "2", "text": "RT @kabar_lembah: air PDAM bau kimia", "created_at": "2026-11-10T15:00:00.000Z",
         "author_id": "u2", "referenced_tweets": [{"type": "retweeted", "id": "1"}],
         "public_metrics": {"like_count": 0, "retweet_count": 5, "reply_count": 0, "quote_count": 0}},
        {"id": "3", "text": "@kabar_lembah serius?", "created_at": "2026-11-10T15:10:00.000Z", "author_id": "u3",
         "referenced_tweets": [{"type": "replied_to", "id": "1"}], "conversation_id": "1"},
    ],
    "includes": {"users": [{"id": "u1", "username": "kabar_lembah", "created_at": "2026-11-01T00:00:00Z"},
                           {"id": "u2", "username": "dodi_ptr"}, {"id": "u3", "username": "sari_n"}],
                 "tweets": [{"id": "1", "text": "air PDAM bau kimia #AirKotaTercemar", "author_id": "u1",
                             "created_at": "2026-11-10T14:41:00.000Z"}]},
    "meta": {"next_token": "abc"},
}
X_PAGE2 = {"data": [{"id": "4", "text": "Pemkot tutup mata #AirKotaTercemar", "created_at": "2026-11-11T00:00:00Z",
                     "author_id": "u4"}], "includes": {"users": [{"id": "u4", "username": "suara_lembah01"}]},
           "meta": {}}

TT_TOKEN = {"access_token": "t", "expires_in": 7200}
TT_VIDEOS = {"data": {"videos": [{"id": 7311, "video_description": "air PDAM bau kimia 😭", "create_time": 1794364200,
                                  "username": "lembahsari.viral", "hashtag_names": ["AirKotaTercemar", "fyp"],
                                  "like_count": 48000, "comment_count": 2, "share_count": 10, "view_count": 900000}],
                      "has_more": False, "cursor": 0, "search_id": "s"}}
TT_COMMENTS = {"data": {"comments": [
    {"id": 9001, "video_id": 7311, "text": "hoax ga sih?", "create_time": 1794364800, "like_count": 3,
     "parent_comment_id": 7311},
    {"id": 9002, "video_id": 7311, "text": "bukan, PDAM udh klarifikasi", "create_time": 1794365000,
     "parent_comment_id": 9001}], "has_more": False}}

APIFY_TWEETS = [{"id": "50", "text": "Kalau benar parah", "createdAt": "Tue Nov 10 15:30:00 +0000 2026",
                 "url": "https://x.com/netizen_kritis/status/50", "twitterUrl": "https://twitter.com/...",
                 "author": {"userName": "netizen_kritis", "followers": 12}, "isQuote": True,
                 "quote": {"id": "1", "text": "air PDAM bau kimia", "createdAt": "Tue Nov 10 14:41:00 +0000 2026",
                           "author": {"userName": "kabar_lembah"}}, "likeCount": 4, "retweetCount": 1}]
APIFY_TT = [{"id": "7311", "text": "air PDAM bau kimia #AirKotaTercemar", "createTimeISO": "2026-11-11T02:30:00.000Z",
             "authorMeta": {"name": "lembahsari.viral"}, "webVideoUrl": "https://www.tiktok.com/@lembahsari.viral/video/7311",
             "diggCount": 48000, "shareCount": 10, "commentCount": 2, "playCount": 900000,
             "hashtags": [{"name": "AirKotaTercemar"}, {"name": "LembahsariDarurat"}]}]
APIFY_TT_C = [{"cid": "777", "text": "serem bgt", "createTimeISO": "2026-11-11T02:40:00.000Z", "uniqueId": "user1234",
               "videoWebUrl": "https://www.tiktok.com/@lembahsari.viral/video/7311", "diggCount": 2},
              {"cid": "778", "text": "iya", "createTimeISO": "2026-11-11T02:41:00.000Z", "uniqueId": "user55",
               "videoWebUrl": "https://www.tiktok.com/@lembahsari.viral/video/7311", "repliesToId": "777"}]


def fake_req(method, url, **kw):
    if "api.x.com" in url:
        return R(X_PAGE2 if kw["params"].get("next_token") else X_PAGE1)
    if "oauth/token" in url:
        return R(TT_TOKEN)
    if "video/query" in url:
        assert kw["json"]["query"]["and"][0]["field_values"] == ["AirKotaTercemar"]
        return R(TT_VIDEOS)
    if "comment/list" in url:
        return R(TT_COMMENTS)
    if "tweet-scraper" in url:
        return R(APIFY_TWEETS)
    if "tiktok-comments-scraper" in url:
        return R(APIFY_TT_C)
    if "tiktok-scraper" in url:
        return R(APIFY_TT)
    raise AssertionError(url)


def main():
    XT._req = fake_req
    XT.time.sleep = lambda s: None

    x = XT.x_api_search("#AirKotaTercemar", "tok", max_items=50)
    ids = {p.id: p for p in x}
    assert set(ids) == {"x:1", "x:2", "x:3", "x:4"}, ids.keys()  # tweet rujukan x:1 ikut masuk
    assert ids["x:2"].kind == "repost" and ids["x:2"].parent_id == "x:1"
    assert ids["x:3"].kind == "reply" and ids["x:1"].author == "kabar_lembah"
    assert ids["x:2"].engagement == 5

    tt = XT.tiktok_research_videos(hashtag="#AirKotaTercemar", key="k", secret="s", start="2026-11-01",
                                   end="2026-11-15", comments_for_top=5)
    tid = {p.id: p for p in tt}
    assert "#airkotatercemar" in tid["tiktok:7311"].text.lower() and tid["tiktok:7311"].author == "lembahsari.viral"
    assert tid["tiktok:c9001"].parent_id == "tiktok:7311"          # komentar → video
    assert tid["tiktok:c9002"].parent_id == "tiktok:c9001"         # balasan → komentar

    ax = XT.x_apify_search("q", "tok")
    assert {p.id for p in ax} == {"x:50", "x:1"} and ax[0].kind == "quote" and ax[0].parent_id == "x:1"
    at = XT.tiktok_apify_search(hashtag="AirKotaTercemar", token="tok")
    aid = {p.id: p for p in at}
    assert aid["tiktok:c777"].parent_id == "tiktok:7311" and aid["tiktok:c778"].parent_id == "tiktok:c777"
    assert "#lembahsaridarurat" in aid["tiktok:7311"].text.lower()

    # import file ekspor (format dikenali otomatis)
    with tempfile.TemporaryDirectory() as d:
        for name, js in [("x.json", X_PAGE1), ("tt.json", APIFY_TT), ("ttc.json", APIFY_TT_C), ("ax.json", APIFY_TWEETS)]:
            with open(os.path.join(d, name), "w") as f:
                json.dump(js, f)
        with open(os.path.join(d, "x_pages.jsonl"), "w") as f:
            f.write(json.dumps(X_PAGE1) + "\n" + json.dumps(X_PAGE2) + "\n")
        assert len(import_file(os.path.join(d, "x.json"))) == 3
        assert len(import_file(os.path.join(d, "x_pages.jsonl"))) == 4
        assert import_file(os.path.join(d, "tt.json"))[0].platform == "tiktok"
        assert import_file(os.path.join(d, "ttc.json"))[1].parent_id == "tiktok:c777"
        assert len(import_file(os.path.join(d, "ax.json"))) == 2

    # analisis gabungan: tweet x:1 harus jadi akar dengan cascade yang mencakup RT, reply, quote
    res = analyze(x + ax + tt + at)
    top = res["origin_candidates"][0]
    assert top["id"] == "x:1", top
    print("OK  —", len(x + ax + tt + at), "post; sumber teratas:", top["author"], top["time"],
          "cascade", top["cascade_size"], top["platforms"])


if __name__ == "__main__":
    main()
