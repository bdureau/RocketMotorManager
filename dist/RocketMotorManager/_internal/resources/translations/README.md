# Translations

The application is written in English. Translations use Qt's `QTranslator`.

`rmm_fr.ts` is the extracted catalogue of every interface string (generated with
`pylupdate6 ui widgets application --ts resources/translations/rmm_fr.ts`), ready
to be translated with **Qt Linguist**.

1. Open `rmm_fr.ts` in Qt Linguist (`pip install pyqt6-tools` or the Qt installer), translate, save.
2. Compile: `lrelease rmm_fr.ts -qm rmm_fr.qm`.
3. Restart the application and choose the language in *Edit > Preferences > General*.

Other languages: copy the `.ts` file as `rmm_<code>.ts` (e.g. `rmm_de.ts`).
