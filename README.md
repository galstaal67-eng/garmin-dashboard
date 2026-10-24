# דשבורד גרמין

דשבורד אישי לנתוני Garmin Connect: אימונים, פעילות יומית (צעדים, דופק מנוחה, דקות עצימות), משקל והרכב גוף.

- `fetch_garmin.py` מושך את הנתונים מ-Garmin Connect (ספריית [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)) ושומר אותם ב-`docs/data.json` וב-`docs/data.js`.
- `docs/index.html` הוא הדשבורד: קובץ אחד, בלי שרת. בלי `data.js` הוא מציג נתוני הדגמה.
- `.github/workflows/sync.yml` מריץ את המשיכה כל בוקר ושומר את הנתונים בריפו.

## התקנה חד-פעמית (במחשב שלך)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python fetch_garmin.py --login
```

הסקריפט שואל אימייל, סיסמה וקוד MFA (אם מופעל), ומדפיס שורת JSON עם טוקנים.
הסיסמה לא נשמרת בשום מקום. הטוקנים נשמרים ב-`~/.garminconnect`.

## סנכרון אוטומטי עם GitHub Actions

1. בריפו: **Settings → Secrets and variables → Actions → New repository secret**
   - `GARMIN_TOKENS` = שורת ה-JSON מהשלב הקודם (מומלץ: לא צריך סיסמה, ועוקף חסימות התחברות של גרמין משרתי GitHub)
   - לחלופין `GARMIN_EMAIL` ו-`GARMIN_PASSWORD` (לא עובד אם יש MFA)
2. **Actions → Sync Garmin data → Run workflow**. ההרצה הראשונה מושכת שנה אחורה (אפשר לשנות בשדה `days`).
3. מכאן זה רץ כל בוקר. הטוקנים המתחדשים נשמרים ב-cache של ה-Action בין ההרצות.

אם הסנכרון נכשל בשגיאת התחברות (למשל אחרי שה-Action לא רץ שבוע וה-cache פג): הריצו שוב `python fetch_garmin.py --login` ועדכנו את הסוד `GARMIN_TOKENS`.

## צפייה בדשבורד

- **מקומית:** `git pull` ואז פתיחת `docs/index.html` בדפדפן (דאבל-קליק).
- **סנכרון מקומי בלי Actions:** `python fetch_garmin.py` ואז לפתוח את `docs/index.html`.
- **GitHub Pages:** Settings → Pages → Branch `main`, תיקייה `/docs`.
  ⚠️ בחשבון GitHub חינמי Pages עובד רק בריפו ציבורי, כלומר נתוני הבריאות שלך יהיו גלויים לכל. השאירו את הריפו פרטי אם זה לא מתאים.

## הערות

- זו גישה לא רשמית ל-Garmin Connect (כמו שהאפליקציה עצמה עושה). גרמין עלולה לשנות את ה-API ואז צריך לעדכן את `garminconnect` ב-`requirements.txt`.
- `python fetch_garmin.py --full --days 730` מושך מחדש שנתיים אחורה.
