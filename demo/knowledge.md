# Facebook Anti-Detection — Deep Dive

**Mục tiêu**: Hiểu Facebook detect bot bằng cách nào ở mỗi layer, từ đó build scraper bền không bị block trong vài ngày/tuần đầu.

> **Key insight**: Facebook KHÔNG dùng 1 signal duy nhất. Họ dùng **risk scoring** — cộng dồn nhiều signal, khi đủ ngưỡng thì checkpoint/ban. Mỗi layer đều quan trọng — fix 1 layer nhưng leak ở layer khác = vẫn bị flag.

---

## Table of Contents

1. [Detection Stack: 6 Layers](#detection-stack-6-layers)
2. [Layer 1: TLS Fingerprinting (JA3/JA4)](#layer-1-tls-fingerprinting)
3. [Layer 2: HTTP Headers](#layer-2-http-headers)
4. [Layer 3: Cookies Deep Dive](#layer-3-cookies-deep-dive)
5. [Layer 4: Browser Fingerprinting](#layer-4-browser-fingerprinting)
6. [Layer 5: Behavioral Patterns](#layer-5-behavioral-patterns)
7. [Layer 6: IP Reputation](#layer-6-ip-reputation)
8. [Tooling Stack Recommendations](#tooling-stack)
9. [Code Examples](#code-examples)
10. [Production Checklist](#production-checklist)

---

## Detection Stack: 6 Layers

Mỗi request đến Facebook đi qua các layer này theo thứ tự. Một layer fail = bị flag, đủ flag = checkpoint.

```
[1] Network: TLS handshake → JA3/JA4 fingerprint
        ↓
[2] HTTP: Headers, order, HTTP/2 settings
        ↓
[3] Application: Cookies (datr, sb, c_user, xs, fr...)
        ↓
[4] Client-side JS: Browser fingerprint (canvas, WebGL, fonts)
        ↓
[5] Behavioral: Click patterns, scroll speed, timing
        ↓
[6] Account: Login history, IP changes, rate limits
```

**Selenium-default fail ngay layer 1**. **bs4 + requests fail ngay layer 1**. Chỉ Playwright/Puppeteer hoặc curl_cffi mới qua được layer 1+2.

---

## Layer 1: TLS Fingerprinting

### Hiểu cơ bản

Khi client kết nối HTTPS, gửi `ClientHello` chứa: TLS version, cipher suites, extensions, elliptic curves theo **thứ tự cụ thể**. Mỗi browser có "chữ ký" riêng. JA3/JA4 hash các field này.

→ Anti-bot biết ông xài Chrome 131 hay là Python `requests` **trước cả khi nhận HTTP request**.

### 2026 Reality Check

Một paper tháng 2/2026 trên arXiv về bot detection qua TLS fingerprint chỉ ra rằng CatBoost classifier dùng JA4 features đạt AUC 0.998 và accuracy 0.9863. Tức là chính xác ~98.6% trong việc detect bot chỉ dùng TLS handshake.

Thêm chiều mới: Post-quantum TLS đã trở thành mặc định cho Akamai từ 31/1/2026. Bot traffic không có PQ key share giờ nằm ngoài baseline "browser thật". Cloudflare cũng đang dùng PQ presence như signal phân loại.

### Test JA3/JA4 của ông

```python
from curl_cffi import requests
r = requests.get("https://tls.peet.ws/api/all", impersonate="chrome")
data = r.json()
print(f"JA3: {data['tls']['ja3_hash']}")
print(f"JA4: {data['tls']['ja4']}")
```

So với JA3/JA4 của Chrome thật → match là OK.

### Solution

| Tool | TLS fingerprint | Verdict |
|---|---|---|
| `requests` (Python) | Python signature, lộ ngay | ❌ |
| `httpx` | Python signature | ❌ |
| `aiohttp` | Python signature | ❌ |
| `curl_cffi` impersonate | Chrome/Safari/Firefox signature thật | ✅ |
| `tls-client` (Go) | Browser signature | ✅ |
| Playwright | Browser TLS thật (Chrome/Firefox/WebKit) | ✅ |
| Selenium | Browser TLS thật | ✅ (tốt ở layer này) |

→ **Cho HTTP-only scraping**: dùng `curl_cffi`. Cho **browser-required**: Playwright.

---

## Layer 2: HTTP Headers

### Headers Facebook check

Facebook không chỉ check User-Agent. Họ check:

1. **Order của headers** — Chrome gửi headers theo thứ tự cụ thể, Python `requests` gửi alphabetically
2. **HTTP/2 SETTINGS frames** — bytes-level signature riêng, JA4 mở rộng có cả phần này
3. **`sec-ch-ua` Client Hints** — Chrome 90+ luôn gửi, nếu UA claim "Chrome 131" mà thiếu `sec-ch-ua` = lộ
4. **`Accept-Language`** — phải match với UA và IP location
5. **`Accept-Encoding`** — Chrome có pattern `gzip, deflate, br, zstd`
6. **`Sec-Fetch-*`** — `Sec-Fetch-Site`, `Sec-Fetch-Mode`, `Sec-Fetch-User`, `Sec-Fetch-Dest` — browser thật luôn gửi
7. **`Referer`** — navigate flow phải hợp lý: từ feed → click vào post → có Referer

### Headers cho Facebook (mobile)

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
```

### Common mistakes

- **UA claim Chrome nhưng thiếu `sec-ch-ua-platform`, `sec-ch-ua-mobile`** → Chrome thật luôn có
- **`Accept-Language: en-US` nhưng IP ở Vietnam** → mismatch
- **Hard-code 1 UA cố định** → 1000 requests cùng UA cùng IP = bot signature
- **Quên `Referer`** khi navigate giữa pages

### curl_cffi tự động xử lý đúng

```python
from curl_cffi import requests
r = requests.get("https://m.facebook.com/nintendo", impersonate="chrome131")
# → Tự động: TLS fingerprint Chrome 131, headers order Chrome, HTTP/2 settings Chrome
```

Đây là lý do `curl_cffi` >> `requests` cho FB.

---

## Layer 3: Cookies Deep Dive

Facebook dùng cookies vừa cho session, vừa cho **device fingerprinting persistent**. Hiểu cookies là **quan trọng nhất** để không bị ban acc.

### Bảng cookies quan trọng

| Cookie | Vai trò | Lifespan | Quan trọng cho bot |
|---|---|---|---|
| **`datr`** | **Browser/device fingerprint, KHÔNG gắn với user** | 2 năm | ⭐⭐⭐⭐⭐ |
| **`sb`** | Browser identification, account recovery | 1 năm | ⭐⭐⭐⭐ |
| **`dbln`** | "Trusted browser" marker | persistent | ⭐⭐⭐⭐ |
| **`c_user`** | User ID đang login | session | ⭐⭐⭐⭐⭐ |
| **`xs`** | Session token (auth) | session | ⭐⭐⭐⭐⭐ |
| **`fr`** | Auth + ads tracking | 90 days | ⭐⭐⭐ |
| **`presence`** | Online status, Messenger | session | ⭐⭐ |
| **`wd`** | Window dimensions | session | ⭐⭐ |
| **`m_pixel_ratio`** | Device pixel ratio | session | ⭐⭐ |
| **`_js_datr`** | JS-set version của datr | session | ⭐⭐⭐ |
| **`oo`** | Ads opt-out | persistent | ⭐ |

### `datr` — Cookie quan trọng nhất

'datr' cookie không chứa thông tin định danh user, nó identify browser được dùng để connect Facebook. Phục vụ ngăn fake account, spam attacks, account theft, DoS attacks.

Meta gán cho browser của ông một fingerprint unique trong 400 ngày qua datr/sb/dbln.

**Practical implication**:
- **Browser mới truy cập FB lần đầu** → FB SET datr mới → "browser này chưa biết, đáng nghi"
- **Browser có datr cũ (>30 ngày, từng login thành công)** → "trusted browser", ít challenge hơn
- **datr thay đổi liên tục giữa các request** → red flag mạnh

→ **Persistent cookies giữa session quan trọng hơn IP**. Nhiều khi đổi IP nhưng giữ datr → vẫn được. Đổi datr với mỗi request → bị flag dù IP đẹp.

### Cookies Cookie security significance

Một CVE năm 2026 cho thấy datr cookie có giá trị lớn đến mức: nếu attacker steal được datr của victim, có thể impersonate trusted device, bypass cả password và 2FA qua flow account recovery.

→ Facebook **rất tin** datr cookie. Đây là 2 mặt: tốt cho ông (giữ datr ổn định = trust cao), nhưng cũng lý do FB monitor datr cực kỹ.

### Cookies vs IP

Đây là điểm nhiều dev hiểu sai:

```
IP đẹp + datr mới + UA random  =  ❌ FB nghi ngay (browser lạ)
IP "trung bình" + datr 6 tháng + UA giữ nguyên  =  ✅ FB tin (browser quen)
```

**Cookies > IP** trong eyes của Facebook trust system.

### Cookies pitfalls khi scrape

1. **Reuse cookies giữa nhiều IP/máy**: 1 cookie set login từ 5 IP khác nhau trong 1h → ban
2. **Mix cookies giữa accounts**: copy datr account A sang account B → check fail
3. **Strip cookies giữa requests**: mỗi request mới → mất state → bị treat như anonymous browser → login wall
4. **Refresh cookies quá nhanh**: clear cookies rồi login lại 10 lần/ngày → checkpoint
5. **Cookies không expired đúng**: browser thật để cookies tự expire, scraper hay clear cookies sớm

### Cookie management đúng

```python
import json
from curl_cffi import requests

# Load cookies từ file (đã warm-up account 7 ngày)
with open("fb_cookies.json") as f:
    cookies_data = json.load(f)

# Tạo persistent session
session = requests.Session()
for c in cookies_data:
    session.cookies.set(c["name"], c["value"], domain=c["domain"])

# Quan trọng: đừng tạo session mới mỗi request
# Đừng clear cookies trừ khi cần force re-login
# Save cookies định kỳ vì FB sẽ refresh/rotate một số

for url in target_urls:
    r = session.get(url, impersonate="chrome131")
    # Process...
    
# Save cookies sau khi xong (FB có thể đã update xs, fr, presence)
import pickle
with open("fb_cookies_updated.pkl", "wb") as f:
    pickle.dump(session.cookies, f)
```

---

## Layer 4: Browser Fingerprinting

Khi browser load FB, các script chạy collect:

1. **Canvas fingerprint** — render text/shape vào canvas, hash → unique per GPU/driver
2. **WebGL fingerprint** — vendor, renderer string, supported extensions
3. **Audio context fingerprint** — sample rate, output latency
4. **Font enumeration** — list fonts cài trên máy
5. **Screen** — `screen.width`, `screen.height`, `availWidth`, `colorDepth`
6. **`navigator`** — `webdriver`, `plugins`, `languages`, `hardwareConcurrency`, `deviceMemory`
7. **Timezone** — `Intl.DateTimeFormat().resolvedOptions().timeZone`
8. **WebRTC** — leak local IP qua STUN
9. **Battery API**, **Permissions API**, etc.

### Selenium leaks

```javascript
navigator.webdriver === true        // Selenium default → ban ngay
window.chrome.runtime undefined     // Chrome thật có
navigator.plugins.length === 0      // bot pattern
```

### playwright-stealth fix gì

`playwright-stealth` patch khoảng 15-20 fingerprint khác nhau:
- `navigator.webdriver = false`
- Fake `navigator.plugins`, `navigator.languages`
- Patch `chrome.runtime`, `chrome.loadTimes`
- WebGL vendor spoofing
- Canvas noise injection

**Limitation**: Cloudflare và Facebook đã biết stealth plugins. Họ check **inconsistencies** chứ không chỉ check 1 flag. Ví dụ:
- UA = "Chrome on Mac" + WebGL renderer = "ANGLE Linux" → mâu thuẫn → flag
- UA = "iPhone Safari" + screen 1920×1080 → impossible → flag

### Solution

1. **Match toàn bộ fingerprint với target device**:
   - UA = Chrome Mac → screen, fonts, WebGL phải match Mac
2. **Anti-detect browser** chuyên dụng:
   - **Multilogin**, **AdsPower**, **Dolphin Anty**, **GoLogin** — sản phẩm thương mại từ $30-100/tháng
   - Tạo profile riêng cho mỗi account, fingerprint isolated, persistent
   - Sophisticated platforms dùng browser fingerprinting, canvas fingerprinting, và hàng chục phương pháp tracking khác mà mobile proxy không defeat được — cần combo browser + IP
3. **DIY với Playwright**: random fingerprint mỗi context nhưng PHẢI persistent trong cùng session

---

## Layer 5: Behavioral Patterns

Facebook dùng ML model phân tích "user behavior profile". Triggers checkpoint:

### Red flags

Facebook checkpoint trigger khi: rapid IP changes, mobile networks dùng CGNAT, frequent Wi-Fi to mobile switches, VPN experimentation; very fast scrolling, repetitive actions, frequent group joins, bulk friend requests, third-party tools làm hành vi resemble automation.

Cụ thể: Logging in/out frequently across many devices, browsers, app instances → giống account sharing/hijacking dù legitimate.

### Quantitative limits (theo experience cộng đồng dev, không official)

| Action | Safe limit | Trigger checkpoint |
|---|---|---|
| Page views | <500/ngày | >2000/ngày |
| Friend requests | <20/ngày | >50/ngày |
| Group joins | <5/ngày | >15/ngày |
| Posts/comments | <20/ngày | >100/ngày |
| Login from new IP | <2/ngày | >5/ngày trong 24h |
| Failed CAPTCHA | 0-1 | >2 → ID verify |
| Cookies clear/rebuild | <1/tuần | nhiều/ngày |

### Pattern detection

FB có ML model học pattern user thật:

- **Scroll behavior**: user thật scroll inconsistent (đọc lúc nhanh lúc chậm), bot scroll uniform
- **Mouse path**: user thật move mouse có jitter, bot move thẳng tắp
- **Click timing**: user click sau khi nhìn (~500ms-2s), bot click ngay (<100ms)
- **Time-of-day**: user thật có pattern (morning/evening), bot online 24/7
- **Session length**: user thật 5-30 phút/session, bot scrape 6 tiếng straight

### Mitigation

```python
import random
import asyncio

async def human_like_scroll(page):
    """Scroll với pattern giống người: tăng tốc, chậm dần, đọc"""
    scroll_distance = random.randint(300, 800)
    duration = random.uniform(0.5, 1.5)
    
    # Scroll smooth thay vì jump
    await page.evaluate(f"""
        window.scrollBy({{
            top: {scroll_distance},
            behavior: 'smooth'
        }});
    """)
    
    # "Đọc" sau khi scroll
    reading_time = random.uniform(2, 6)
    await asyncio.sleep(reading_time)
    
    # Đôi khi hover element (simulate đọc)
    if random.random() < 0.3:
        await page.mouse.move(
            random.randint(100, 1200),
            random.randint(200, 600),
            steps=random.randint(5, 15),  # smooth movement
        )

async def session_with_breaks(scrape_func, target):
    """Session 15-30 phút rồi break 1-3 tiếng"""
    session_duration = random.randint(15, 30) * 60
    break_duration = random.randint(60, 180) * 60
    
    start = time.time()
    while time.time() - start < session_duration:
        await scrape_func(target)
        await asyncio.sleep(random.uniform(30, 120))
    
    print(f"Break {break_duration/60:.0f} min...")
    await asyncio.sleep(break_duration)
```

### Time-of-day patterns

Đừng scrape 24/7. Mimic timezone của account:

```python
import datetime

def is_active_hour(timezone_offset=7):  # VN = UTC+7
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=timezone_offset)
    hour = now.hour
    # Active 7am-11pm, peak 12-14h và 19-22h
    if hour < 7 or hour > 23:
        return False, 0  # ngủ
    elif 12 <= hour <= 14 or 19 <= hour <= 22:
        return True, 1.0  # peak
    else:
        return True, 0.5  # off-peak

async def time_aware_scraper():
    while True:
        active, intensity = is_active_hour()
        if not active:
            await asyncio.sleep(3600)  # ngủ 1h
            continue
        
        # Scrape ít hơn khi off-peak
        delay = random.uniform(60, 300) / intensity
        await asyncio.sleep(delay)
        await scrape_one()
```

---

## Layer 6: IP Reputation

### Hierarchy of IP trust (cao → thấp)

Mobile IPs route qua cellular networks 4G/5G với CGNAT có trust score cao do nhiều user share IP. Platforms như Instagram, TikTok, Facebook optimize cho mobile users → mobile IPs appear natural hơn với 95-99% success rate so với 85-92% cho residential proxies.

| IP type | Trust với FB | Cost | Use case |
|---|---|---|---|
| **Mobile (4G/5G)** | ⭐⭐⭐⭐⭐ | $50-100/proxy/mo | Multi-account, scrape nặng |
| **Residential** | ⭐⭐⭐⭐ | $3-15/GB | Scrape chuẩn |
| **ISP (static residential)** | ⭐⭐⭐⭐ | $0.5-3/IP/mo | Account warm-up, persistent |
| **Datacenter** | ⭐ | $1-3/IP/mo | Test only, FB block ngay |
| **VPN consumer (NordVPN, etc.)** | ❌ | - | FB block hết |

### Tại sao mobile = best

Facebook trust systems heavily favor mobile carrier IPs vì represent real users on legitimate mobile networks. Mobile networks dùng CGNAT mà Facebook implicitly trust. Mobile connection patterns match Facebook app usage.

CGNAT = nhiều user share 1 public IP qua NAT của carrier → FB không thể ban 1 IP vì sẽ block hàng nghìn user thật.

### IP rotation strategy

**❌ Sai**: rotate IP mỗi request → FB thấy 1 user "teleport" giữa các nước

**✅ Đúng**: 
- 1 account = 1 IP "sticky" trong session (15-60 phút)
- Cookies + IP cùng vùng địa lý
- Đổi IP chỉ khi đổi session/ngày, và đổi sang IP CÙNG city/country

### Provider recommendations cho Facebook

| Provider | Type | Price | Note |
|---|---|---|---|
| **Bright Data** | All types | $$$$ | Enterprise, best success rate |
| **Decodo (Smartproxy)** | Residential | $$ | Balance price/quality |
| **NodeMaven** | Mobile/Residential | $$$ | Stealth optimized |
| **IPRoyal** | Residential | $$ | Có sticky session |
| **SOAX** | Mobile/Residential | $$$ | Geo-targeting tốt |
| **NetNut** | ISP | $$$ | Cleanest residential |

Cho FB scraping VN: bắt đầu với **Decodo residential, sticky session 30min, geo-target VN**. Khi scale lên thì up mobile.

---

## Tooling Stack Recommendations

### Stack 1: HTTP-only (rẻ, fast, public content)

```
curl_cffi (TLS impersonate)  
  + persistent session (cookies)  
  + residential proxy (sticky)  
  + m.facebook.com endpoint
```

Use case: scrape public pages, không cần JS, scale lớn.

**Code template**: xem [Code Examples](#code-examples) section.

### Stack 2: Browser-based (private content, JS required)

```
Playwright (Chromium, real TLS)
  + playwright-stealth (fingerprint patches)
  + persistent context (cookies + localStorage)
  + residential/mobile proxy
  + human-like behavior
```

Use case: scrape group private, content cần JS render.

### Stack 3: Anti-detect browser (multi-account, production)

```
Multilogin / AdsPower / Dolphin Anty
  + mobile proxy per profile
  + Playwright drive
```

Use case: manage 10+ accounts cho production.

### Stack 4: Outsource (zero maintenance)

```
Apify Facebook Scraper / Bright Data Web Unlocker
```

Use case: không muốn touch infra.

---

## Code Examples

### Example 1: HTTP scrape với curl_cffi (best practice)

```python
import json
import time
import random
import pickle
from pathlib import Path
from curl_cffi import requests

class FacebookScraper:
    def __init__(self, cookies_path, proxy=None, ua_locale="en-US"):
        self.cookies_path = Path(cookies_path)
        self.session = requests.Session()
        self.proxy = proxy
        self.ua_locale = ua_locale
        self._load_cookies()
    
    def _load_cookies(self):
        if self.cookies_path.exists():
            with open(self.cookies_path, "rb") as f:
                self.session.cookies.update(pickle.load(f))
            print(f"Loaded {len(self.session.cookies)} cookies")
    
    def _save_cookies(self):
        with open(self.cookies_path, "wb") as f:
            pickle.dump(self.session.cookies, f)
    
    def _get_headers(self):
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self.ua_locale},en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
    
    def get(self, url, **kwargs):
        # Random delay 2-7s
        time.sleep(random.uniform(2, 7))
        
        kwargs.setdefault("impersonate", "chrome131")
        kwargs.setdefault("headers", self._get_headers())
        kwargs.setdefault("timeout", 30)
        
        if self.proxy:
            kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        
        r = self.session.get(url, **kwargs)
        
        # Save cookies sau request (FB có thể update xs, presence...)
        self._save_cookies()
        
        # Detect checkpoint
        if "checkpoint" in r.url or "login" in r.url:
            raise Exception(f"BLOCKED: redirected to {r.url}")
        if r.status_code in (403, 429):
            raise Exception(f"BLOCKED: status {r.status_code}")
        
        return r
    
    def scrape_page(self, page_username):
        # Mobile FB serves cleaner HTML
        url = f"https://m.facebook.com/{page_username}"
        r = self.get(url)
        
        # Parse với bs4 hoặc selectolax
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        
        posts = []
        for article in soup.find_all("article"):
            text = article.get_text(strip=True)[:500]
            posts.append({"text": text})
        
        return posts


# Usage
scraper = FacebookScraper(
    cookies_path="fb_cookies.pkl",
    proxy="http://user:pass@gate.decodo.com:7000",
    ua_locale="en-US",
)

posts = scraper.scrape_page("nintendo")
for p in posts[:5]:
    print(p["text"][:200])
```

### Example 2: Playwright stealth + behavior simulation

```python
import asyncio
import random
import json
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

class StealthFBScraper:
    def __init__(self, cookies_file, proxy=None):
        self.cookies_file = cookies_file
        self.proxy = proxy
    
    async def _setup_context(self, browser):
        context_options = {
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "color_scheme": "light",
            "device_scale_factor": 2,  # Retina
        }
        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}
        
        context = await browser.new_context(**context_options)
        
        # Load cookies
        with open(self.cookies_file) as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        
        return context
    
    async def _human_scroll(self, page, num_scrolls=5):
        for i in range(num_scrolls):
            # Random scroll distance (giống đọc)
            distance = random.randint(300, 800)
            await page.evaluate(f"""
                window.scrollBy({{ top: {distance}, behavior: 'smooth' }});
            """)
            
            # Reading time
            await asyncio.sleep(random.uniform(2, 5))
            
            # Đôi khi move mouse (simulate reading)
            if random.random() < 0.4:
                await page.mouse.move(
                    random.randint(200, 1100),
                    random.randint(200, 600),
                    steps=random.randint(10, 25),
                )
                await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Đôi khi hover element ngẫu nhiên
            if random.random() < 0.2:
                articles = await page.query_selector_all('div[role="article"]')
                if articles:
                    target = random.choice(articles)
                    await target.hover()
                    await asyncio.sleep(random.uniform(1, 3))
    
    async def scrape(self, url):
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = await self._setup_context(browser)
            page = await context.new_page()
            
            # Navigate với realistic timing
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(3, 6))  # đọc đầu trang
            
            # Human-like scroll
            await self._human_scroll(page, num_scrolls=random.randint(3, 8))
            
            # Extract data
            articles = await page.query_selector_all('div[role="article"]')
            posts = []
            for article in articles[:20]:
                text = await article.inner_text()
                posts.append({"text": text[:500]})
            
            # Save cookies updated
            cookies = await context.cookies()
            with open(self.cookies_file, "w") as f:
                json.dump(cookies, f)
            
            await browser.close()
            return posts


# Usage
async def main():
    scraper = StealthFBScraper(
        cookies_file="fb_cookies.json",
        proxy="http://user:pass@gate.decodo.com:7000",
    )
    posts = await scraper.scrape("https://www.facebook.com/nintendo")
    print(f"Got {len(posts)} posts")

asyncio.run(main())
```

### Example 3: Account warm-up automation

```python
import random
import asyncio
from datetime import datetime, timedelta

class AccountWarmer:
    """Warm up burner FB account để build trust với datr/sb cookie"""
    
    def __init__(self, scraper):
        self.scraper = scraper
        self.actions_today = 0
    
    async def daily_routine(self, day_number):
        """Mỗi ngày tăng dần activity, theo schedule realistic"""
        
        if day_number <= 2:
            # Day 1-2: chỉ browse, không tương tác
            await self._browse_feed(min_minutes=5, max_minutes=10)
        
        elif day_number <= 4:
            # Day 3-4: browse + like vài post
            await self._browse_feed(min_minutes=10, max_minutes=15)
            await self._like_random_posts(count=random.randint(3, 7))
        
        elif day_number <= 6:
            # Day 5-6: + add bạn, join group
            await self._browse_feed(min_minutes=10, max_minutes=20)
            await self._like_random_posts(count=random.randint(5, 10))
            if random.random() < 0.5:
                await self._add_friends(count=random.randint(2, 5))
        
        else:
            # Day 7+: full activity, có thể scrape
            await self._browse_feed(min_minutes=5, max_minutes=15)
            await self._like_random_posts(count=random.randint(2, 8))
        
        print(f"Day {day_number} routine done")
    
    async def _browse_feed(self, min_minutes, max_minutes):
        duration = random.randint(min_minutes, max_minutes) * 60
        end_time = datetime.now() + timedelta(seconds=duration)
        
        while datetime.now() < end_time:
            # Vào newsfeed
            await self.scraper.goto("https://www.facebook.com/")
            await self.scraper.human_scroll(random.randint(3, 8))
            await asyncio.sleep(random.uniform(30, 90))
    
    # ... các method khác

# Usage: chạy 1 lần/ngày trong 7 ngày trước khi scrape thật
```

---

## Production Checklist

Trước khi deploy scraper vào production, check tất cả:

### Network layer

- [ ] HTTP client KHÔNG phải `requests`/`httpx`/`aiohttp` thuần
- [ ] Dùng `curl_cffi` với `impersonate="chrome131"` HOẶC Playwright/Puppeteer
- [ ] Verify JA3/JA4 fingerprint match Chrome thật (test ở `tls.peet.ws`)

### Headers layer

- [ ] User-Agent + sec-ch-ua + Accept-Language consistent
- [ ] Accept-Language match với IP geolocation
- [ ] Sec-Fetch-* headers có đủ
- [ ] Referer hợp lý theo flow

### Cookies layer

- [ ] Account đã warm-up tối thiểu 7 ngày
- [ ] Cookies persistent giữa các session
- [ ] datr cookie KHÔNG đổi giữa các request
- [ ] Save cookies sau mỗi request (FB rotate xs, fr, presence)
- [ ] KHÔNG share cookies giữa nhiều IP/account

### Browser fingerprint layer

- [ ] `navigator.webdriver = false` (playwright-stealth)
- [ ] Canvas/WebGL/Audio fingerprint stable per session
- [ ] Screen size + DPR match UA
- [ ] Timezone match IP location

### Behavioral layer

- [ ] Random delay 2-7s giữa requests
- [ ] Human-like scroll (smooth, không uniform)
- [ ] Mouse movement với jitter
- [ ] Session 15-30 phút, break 1-3h
- [ ] Active hours match timezone (không scrape 24/7)
- [ ] Daily action limit < 500 page views/account

### IP layer

- [ ] Mobile hoặc Residential proxy (KHÔNG datacenter)
- [ ] Sticky session 15-60 phút (không rotate per request)
- [ ] Geo-target match với account location
- [ ] 1 account = 1 IP per session

### Account layer

- [ ] Account warm-up hoàn tất (>7 ngày)
- [ ] Có profile picture, info cơ bản, vài bạn, vài group
- [ ] KHÔNG dùng SĐT/email pattern lạ
- [ ] Có 2-3 burner backup nếu account chính fail
- [ ] Monitor checkpoint signals → STOP ngay khi gặp CAPTCHA liên tục

### Scale layer

- [ ] Khi scale: 1 account → tối đa scrape 200-500 page/ngày
- [ ] Cần nhiều hơn → tăng accounts, không tăng requests/account
- [ ] Multi-account: dùng anti-detect browser hoặc isolated environments

---

## Common failure modes

### "TemporarilyBanned" / 403

**Cause**: IP flagged, rate limit, hoặc fingerprint inconsistency

**Fix**:
1. Stop ngay 1-24h
2. Đổi IP (cùng geo)
3. Verify cookies còn valid
4. Check JA3 với `tls.peet.ws`

### Login wall trên public page

**Cause**: Anonymous request bị FB ép login để track

**Fix**:
1. Dùng `m.facebook.com` thay vì `www.facebook.com`
2. Dùng cookies của warm-up account
3. Slow down + thêm delay

### Checkpoint "Confirm your identity"

**Cause**: Behavioral pattern nghi ngờ, hoặc IP/device change đột ngột

**Fix**:
1. STOP scraping account này ngay
2. Login bằng tay từ device thường, complete checkpoint
3. KHÔNG scrape account này 1-2 tuần sau đó
4. Move sang burner khác

### Cookies "expired" mỗi vài giờ

**Cause**: FB invalidate session vì detect bot

**Fix**:
1. Increase delay, decrease frequency
2. Browser fingerprint chưa đủ stealth
3. Có thể IP đã bị flag — đổi IP

---

## TL;DR — 5 Rules Cốt Lõi

1. **Cookies > IP**: persistent datr/sb cookie từ account warm-up quan trọng hơn proxy đẹp
2. **TLS layer first**: nếu scrape HTTP-only, dùng `curl_cffi` chứ không phải `requests`
3. **Mobile FB > Desktop FB**: `m.facebook.com` ít defense hơn nhiều
4. **Behavioral matters**: 1 account/ngày scrape 200 page với human pattern > 2000 page với uniform timing
5. **Don't fight Facebook detection alone**: Apify/Bright Data có team dedicated $50M/year — ông không win solo war này, chỉ blend in được thôi

---

## References

- TLS fingerprinting: [Scrapfly's JA3/JA4 guide](https://scrapfly.io/web-scraping-tools/ja3-fingerprint)
- curl_cffi docs: [curl-cffi.readthedocs.io](https://curl-cffi.readthedocs.io/)
- Cookie analysis: [Captain Compliance Facebook cookies](https://captaincompliance.com/education/datr-cookie/)
- Anti-detect browsers: Multilogin, AdsPower, Dolphin Anty, GoLogin
- Proxy testing: NodeMaven, Decodo, Bright Data