# راهنمای نصب و راه‌اندازی ربات اینستاگرام

## مرحله 1: ایجاد پوشه‌های مورد نیاز

ابتدا باید پوشه‌های زیر را برای ذخیره‌سازی داده‌ها ایجاد کنید:

```
mkdir -p postgres_data
mkdir -p sessions
mkdir -p logs
mkdir -p data
```

سپس دسترسی کامل را به این پوشه‌ها اختصاص دهید:

```
chmod -R 777 postgres_data
chmod -R 777 sessions
chmod -R 777 logs
chmod -R 777 data
```

## مرحله 2: تنظیم فایل .env

یک فایل `.env` در مسیر اصلی ایجاد کنید و اطلاعات زیر را در آن قرار دهید:

```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=postgres
DB_PORT=5432
DB_NAME=instagrambot
DAILY_FOLLOW_LIMIT=5
DAILY_UNFOLLOW_LIMIT=5
DAILY_LIKE_LIMIT=15
DAILY_COMMENT_LIMIT=2
DAILY_DIRECT_LIMIT=1
DAILY_STORY_REACTION_LIMIT=3
```

نام کاربری و رمز عبور خود را در فایل وارد کنید.

## مرحله 3: راه‌اندازی با داکر

اول هر کانتینر موجود را متوقف کنید:

```
docker-compose down
```

سپس کانتینرها را بسازید و اجرا کنید:

```
docker-compose up -d --build
```

## مرحله 4: بررسی وضعیت

برای بررسی وضعیت کانتینرها:

```
docker-compose ps
```

## مرحله 5: دسترسی به رابط کاربری

پس از راه‌اندازی موفق، می‌توانید به رابط کاربری در آدرس زیر دسترسی پیدا کنید:

```
http://localhost:8000
```

## عیب‌یابی

اگر با مشکلی مواجه شدید، لاگ‌ها را بررسی کنید:

```
docker-compose logs -f
```

## بازنشانی دیتابیس (در صورت نیاز)

اگر می‌خواهید دیتابیس را به طور کامل بازنشانی کنید:

```
docker-compose down
rm -rf postgres_data/*
docker-compose up -d
```

توجه: این کار باعث حذف تمام داده‌های موجود می‌شود!