# דשבורד גרמין

דשבורד אישי לנתוני Garmin Connect: אימונים, פעילות יומית (צעדים, דופק מנוחה, דקות עצימות), משקל והרכב גוף.

| קובץ | תפקיד |
|---|---|
| `fetch_garmin.py` | מושך נתונים מ-Garmin Connect אל `data/garmin.json` |
| `.github/workflows/sync.yml` | מריץ את המשיכה כל בוקר ושומר את `data/garmin.json` בריפו (הפרטי) |
| `docs/index.html` | הדשבורד |
| `scripts/encrypt-data.mjs` + `netlify.toml` | בבנייה ב-Netlify: מצפין את הנתונים (ואת מפתח ה-GitHub) בסיסמה ומפרסם רק את `docs/` |
| `scripts/should-build.mjs` | מדלג על בנייה ב-Netlify כשהשתנו רק נתונים (כשיש מפתח GitHub) |

הנתונים הגולמיים לא מתפרסמים. האתר ב-Netlify מקבל רק עותק מוצפן (AES-256), והדפדפן מפענח אותו אחרי הזנת סיסמה.

## 1. התחברות לגרמין (פעם אחת, במחשב שלך)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-sync.txt
python fetch_garmin.py --login
```

הסקריפט שואל אימייל, סיסמה וקוד MFA (אם מופעל), ומדפיס שורת JSON עם טוקנים. הסיסמה לא נשמרת.

## 2. סנכרון יומי ב-GitHub

1. **Settings → Secrets and variables → Actions → New repository secret**: `GARMIN_TOKENS` = שורת ה-JSON מהשלב הקודם.
2. **Actions → Sync Garmin data → Run workflow**. ההרצה הראשונה מושכת שנה אחורה.

אם הסנכרון נכשל בשגיאת התחברות: מריצים שוב `python fetch_garmin.py --login` ומעדכנים את `GARMIN_TOKENS`.

## 3. Netlify

1. **Add new project → Import an existing project → GitHub** ובוחרים את `garmin-dashboard` (ההגדרות נקראות מ-`netlify.toml`).
2. **Site configuration → Environment variables → Add a variable**: `DASHBOARD_PASSWORD` = הסיסמה לדשבורד.
3. **Deploys → Trigger deploy**.

בלי `DASHBOARD_PASSWORD` הבנייה נכשלת בכוונה, כדי שלא יתפרסם שום דבר לא מוצפן.

## 4. נתונים חיים וכפתור "סנכרון" (מומלץ)

בתוכנית החינמית של Netlify יש כ-20 פרסומים בחודש, והסנכרון היומי לבדו צורך 30. עם מפתח GitHub, הדף טוען את הנתונים ישירות מהריפו הפרטי, Netlify לא בונה מחדש על כל שינוי נתונים, ומופיע כפתור **⟳ סנכרון** שמפעיל סנכרון מגרמין ומרענן את המסך.

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
   - **Repository access**: Only select repositories → `garmin-dashboard`
   - **Permissions**: `Contents` = Read-only, `Actions` = Read and write
   - **Expiration**: עד שנה (צריך לחדש כשפג)
2. Netlify → **Site configuration → Environment variables**: `DASHBOARD_GITHUB_TOKEN` = הטוקן.
3. **Deploys → Trigger deploy**.

המפתח נשמר רק בתוך החבילה המוצפנת בסיסמת הדשבורד, ומי שאין לו את הסיסמה לא יכול לקרוא אותו.

## צפייה מקומית

`python fetch_garmin.py` ואז פתיחת `docs/index.html` (הקובץ `docs/data.js` שנוצר מקומית לא מוצפן ולא נכנס ל-git).
