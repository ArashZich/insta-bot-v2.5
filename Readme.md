# راهنمای کامل API ربات اینستاگرام

این راهنما توضیح می‌دهد که چگونه از API ربات اینستاگرام استفاده کنید. API ربات مجموعه‌ای از اندپوینت‌ها را ارائه می‌دهد که به شما امکان کنترل، مانیتورینگ و مدیریت ربات را می‌دهد.

## پیش‌نیازها

- ربات اینستاگرام نصب شده و فعال باشد
- دسترسی به آدرس `http://localhost:8000` یا سرور مربوطه

## فهرست API‌ها

### 1. مدیریت و کنترل ربات

#### وضعیت فعلی ربات
```
GET /api/status
```
برای دریافت وضعیت کنونی ربات، شامل وضعیت اجرا، ورود به سیستم، آخرین فعالیت و محدودیت‌های روزانه.

**مثال پاسخ:**
```json
{
  "running": true,
  "logged_in": true,
  "session_active": true,
  "daily_limits": {
    "follows": 5,
    "unfollows": 3,
    "likes": 12,
    "comments": 2,
    "directs": 1,
    "story_reactions": 8
  },
  "last_activity": "2025-03-20T15:40:28.123456"
}
```

#### کنترل ربات
```
POST /api/control
```
برای شروع، توقف یا راه‌اندازی مجدد ربات.

**پارامترها (JSON):**
```json
{
  "action": "start" // یکی از سه مقدار: "start"، "stop" یا "restart"
}
```

**مثال پاسخ:**
```json
{
  "success": true,
  "message": "Bot started successfully",
  "status": true
}
```

#### راه‌اندازی مجدد ربات (ساده)
```
GET /api/restart-bot
```
راه‌اندازی مجدد ربات با استفاده از درخواست GET ساده، بدون نیاز به ارسال JSON.

**مثال پاسخ:**
```json
{
  "success": true,
  "message": "Bot restarted successfully",
  "status": true,
  "details": "This is a GET endpoint that restarts the bot. You can check the current status at /api/status."
}
```

#### آزادسازی اجباری قفل
```
GET /api/force-unlock
```
آزادسازی اجباری قفل در صورتی که ربات در حالت قفل گیر کرده باشد.

**مثال پاسخ:**
```json
{
  "success": true,
  "message": "Bot lock forcibly released"
}
```

### 2. آمار و گزارش‌ها

#### آمار فعالیت‌ها
```
POST /api/stats
```
دریافت آمار فعالیت‌های ربات در بازه‌های زمانی مختلف.

**پارامترها (JSON):**
```json
{
  "period": "daily" // یکی از چهار مقدار: "daily"، "weekly"، "monthly" یا "six_months"
}
```

**مثال پاسخ:**
```json
{
  "period": "daily",
  "follows": 5,
  "unfollows": 3,
  "likes": 12,
  "comments": 2,
  "directs": 1,
  "story_reactions": 8,
  "followers_gained": 7,
  "followers_lost": 2,
  "days": 1,
  "avg_follows": 5.0,
  "avg_unfollows": 3.0,
  "avg_likes": 12.0,
  "avg_comments": 2.0,
  "avg_directs": 1.0,
  "avg_story_reactions": 8.0,
  "avg_followers_gained": 7.0,
  "avg_followers_lost": 2.0
}
```

### 3. مشاهده فعالیت‌ها و دنبال‌کنندگان

#### لیست فعالیت‌های ربات
```
GET /api/activities
```
دریافت لیست فعالیت‌های ربات با امکان فیلتر کردن.

**پارامترهای Query:**
- `activity_type` (اختیاری): نوع فعالیت، یکی از: `follow`, `unfollow`, `like`, `comment`, `direct`, `story_reaction`
- `status` (اختیاری): وضعیت فعالیت، یکی از: `success`, `failed`
- `period` (اختیاری، پیش‌فرض: `last_7_days`): بازه زمانی، یکی از: `today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `last_7_days`, `last_30_days`, `last_90_days`, `this_year`, `all_time`
- `page` (اختیاری، پیش‌فرض: `1`): شماره صفحه
- `size` (اختیاری، پیش‌فرض: `20`): تعداد آیتم در هر صفحه (حداکثر 100)

**مثال:**
```
GET /api/activities?activity_type=like&status=success&period=today&page=1&size=10
```

**مثال پاسخ:**
```json
{
  "activities": [
    {
      "id": 123,
      "activity_type": "like",
      "target_user_id": "12345678",
      "target_user_username": "example_user",
      "target_media_id": "2068536123456789123",
      "status": "success",
      "details": null,
      "created_at": "2025-03-20T15:30:45.123456"
    },
    // ...
  ],
  "total": 42,
  "page": 1,
  "size": 10
}
```

#### لیست کاربران فالو شده
```
GET /api/followings
```
دریافت لیست کاربرانی که ربات فالو/آنفالو کرده است.

**پارامترهای Query:**
- `is_following` (اختیاری): وضعیت فالو، `true` یا `false`
- `followed_back` (اختیاری): آیا کاربر متقابلاً فالو کرده، `true` یا `false`
- `period` (اختیاری، پیش‌فرض: `last_7_days`): بازه زمانی، یکی از: `today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `last_7_days`, `last_30_days`, `last_90_days`, `this_year`, `all_time`
- `page` (اختیاری، پیش‌فرض: `1`): شماره صفحه
- `size` (اختیاری، پیش‌فرض: `20`): تعداد آیتم در هر صفحه (حداکثر 100)

**مثال:**
```
GET /api/followings?is_following=true&followed_back=false&period=last_30_days&page=1&size=10
```

**مثال پاسخ:**
```json
{
  "followings": [
    {
      "id": 42,
      "user_id": "12345678",
      "username": "example_user",
      "followed_at": "2025-03-15T10:30:45.123456",
      "unfollowed_at": null,
      "is_following": true,
      "followed_back": false
    },
    // ...
  ],
  "total": 35,
  "page": 1,
  "size": 10
}
```

## نمونه‌های کاربردی

### 1. راه‌اندازی ربات با cURL

```bash
# شروع ربات
curl -X POST "http://localhost:8000/api/control" \
     -H "Content-Type: application/json" \
     -d '{"action": "start"}'

# توقف ربات
curl -X POST "http://localhost:8000/api/control" \
     -H "Content-Type: application/json" \
     -d '{"action": "stop"}'

# راه‌اندازی مجدد ربات (روش ساده)
curl "http://localhost:8000/api/restart-bot"
```

### 2. بررسی آمار ربات با Python

```python
import requests
import json

# دریافت آمار هفتگی
response = requests.post(
    "http://localhost:8000/api/stats",
    json={"period": "weekly"}
)

stats = response.json()
print(f"در هفته گذشته:")
print(f"تعداد فالو: {stats['follows']}")
print(f"تعداد لایک: {stats['likes']}")
print(f"فالوئرهای جدید: {stats['followers_gained']}")
print(f"فالوئرهای از دست رفته: {stats['followers_lost']}")
```

### 3. دریافت فعالیت‌های امروز با JavaScript

```javascript
// دریافت فعالیت‌های موفق امروز
fetch('http://localhost:8000/api/activities?period=today&status=success')
  .then(response => response.json())
  .then(data => {
    console.log(`تعداد کل فعالیت‌های موفق امروز: ${data.total}`);
    console.log('فعالیت‌های اخیر:');
    data.activities.forEach(activity => {
      console.log(`- ${activity.activity_type} برای کاربر ${activity.target_user_username} در ${new Date(activity.created_at).toLocaleTimeString()}`);
    });
  })
  .catch(error => console.error('خطا:', error));
```

### 4. اسکریپت پایش سلامت ربات

```python
import requests
import time
from datetime import datetime, timedelta

def check_bot_health():
    # دریافت وضعیت ربات
    response = requests.get("http://localhost:8000/api/status")
    status = response.json()
    
    # بررسی وضعیت اجرا
    if not status["running"]:
        print("هشدار: ربات در حال اجرا نیست!")
        # راه‌اندازی مجدد ربات
        restart = requests.get("http://localhost:8000/api/restart-bot")
        print(f"نتیجه راه‌اندازی مجدد: {restart.json()['message']}")
        return
    
    # بررسی آخرین فعالیت
    if status["last_activity"]:
        last_activity = datetime.fromisoformat(status["last_activity"].replace('Z', '+00:00'))
        now = datetime.now(last_activity.tzinfo)
        
        # اگر بیش از 2 ساعت از آخرین فعالیت گذشته باشد
        if (now - last_activity) > timedelta(hours=2):
            print(f"هشدار: ربات برای {(now - last_activity).total_seconds() / 3600:.1f} ساعت غیرفعال بوده است!")
            # آزادسازی اجباری قفل
            unlock = requests.get("http://localhost:8000/api/force-unlock")
            print(f"نتیجه آزادسازی قفل: {unlock.json()['message']}")
            
            # راه‌اندازی مجدد ربات
            restart = requests.get("http://localhost:8000/api/restart-bot")
            print(f"نتیجه راه‌اندازی مجدد: {restart.json()['message']}")
        else:
            print(f"ربات سالم است. آخرین فعالیت: {last_activity}")
    else:
        print("هشدار: ربات هنوز هیچ فعالیتی انجام نداده است!")

# اجرا هر 30 دقیقه
while True:
    check_bot_health()
    time.sleep(30 * 60)
```

## دسترسی به رابط گرافیکی

برای استفاده از رابط گرافیکی ساده، به آدرس زیر مراجعه کنید:
```
http://localhost:8000/
```

این رابط به شما امکان می‌دهد ربات را کنترل کنید، وضعیت آن را بررسی کنید و فعالیت‌های اخیر را مشاهده کنید.

## توصیه‌های امنیتی

1. **دسترسی محدود**: API ربات را در معرض اینترنت قرار ندهید. ترجیحاً آن را فقط روی لوکال‌هاست یا در شبکه داخلی قرار دهید.

2. **نظارت مداوم**: برای اطمینان از عملکرد صحیح ربات، به صورت منظم آن را بررسی کنید.

3. **محدودیت‌های روزانه**: برای جلوگیری از محدودیت حساب اینستاگرام، محدودیت‌های روزانه را متناسب تنظیم کنید.

4. **بکاپ منظم**: از اطلاعات پایگاه داده و تنظیمات خود به صورت منظم بکاپ تهیه کنید.

## عیب‌یابی رایج

1. **ربات پاسخ نمی‌دهد**:
   - `/api/status` را بررسی کنید تا ببینید آیا ربات در حال اجراست.
   - بررسی کنید که کانتینر داکر در حال اجرا باشد.
   - لاگ‌ها را با استفاده از دستور `docker logs instagram_bot` بررسی کنید.

2. **ربات در حالت استراحت گیر کرده**:
   - از اندپوینت `/api/force-unlock` برای آزادسازی قفل استفاده کنید.
   - سپس از `/api/restart-bot` برای راه‌اندازی مجدد ربات استفاده کنید.

3. **خطای دیتابیس**:
   - بررسی کنید که کانتینر PostgreSQL در حال اجرا باشد.
   - متغیرهای محیطی مرتبط با دیتابیس را در فایل `.env` بررسی کنید.

4. **ربات ورود نمی‌کند**:
   - نام کاربری و رمز عبور را در فایل `.env` بررسی کنید.
   - لاگ‌های `instagram_client.log` را برای پیام‌های خطا بررسی کنید.

---

امیدوارم این راهنما به شما در استفاده بهینه از API ربات اینستاگرام کمک کند. برای سوالات یا مشکلات بیشتر، لطفاً به لاگ‌های ربات مراجعه کنید یا با توسعه‌دهندگان تماس بگیرید.