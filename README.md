<img width="981" height="811" alt="image" src="https://github.com/user-attachments/assets/2f2031ec-3394-4814-bb58-727e0716576c" />
  English: Anonymous-Security-Suite Overview
Anonymous-Security-Suite is a powerful offline desktop application designed to automatically redact sensitive personal information (PII) from documents without relying on cloud services, ensuring maximum data privacy.

Key Features:

Deep Anonymization: Automatically detects and redacts names, addresses, company details, financial numbers (IBAN), and IDs (PESEL, NIP, etc.) using a combination of AI (spaCy, Transformers) and Regular Expressions.

OCR & Logo Detection: Uses Tesseract OCR to extract text from scanned PDFs and OpenCV to locate and redact company logos via template matching.

Hot Folder (Auto-mode): A background Watchdog process continuously monitors a selected folder. Any new file dropped into this directory is automatically anonymized without manual intervention.

Context Menu Integration: Seamlessly integrates with Windows OS. You can right-click any supported file (.pdf, .docx, .txt) and select "Anonymize" directly from the context menu.

Smart RAM Management: In standby mode, with AI models loaded for instant processing, the app uses about 1.4 GB of RAM. However, to save system resources, it features a smart "sleep mode"—after 5 minutes of inactivity, the heavy AI models are automatically unloaded from memory, minimizing resource consumption until the next task arrives.

  Polski: Opis Anonymous-Security-Suite
Anonymous-Security-Suite to potężna aplikacja desktopowa działająca całkowicie offline, zaprojektowana do automatycznego usuwania wrażliwych danych osobowych (PII) z dokumentów. Gwarantuje maksymalną prywatność, nie wysyłając żadnych danych do chmury.

Kluczowe funkcje:

Głęboka anonimizacja: Automatycznie wykrywa i zamazuje imiona, nazwiska, adresy, dane firmowe, numery kont (IBAN) oraz identyfikatory (PESEL, NIP itp.) przy użyciu sztucznej inteligencji (spaCy, Transformers) i wyrażeń regularnych.

Wsparcie OCR i wykrywanie logo: Wykorzystuje Tesseract OCR do wyciągania tekstu ze skanów PDF oraz OpenCV do znajdowania i cenzurowania logotypów.

Gorący folder (Tryb Auto): Proces działający w tle (Watchdog) stale monitoruje wybrany katalog. Każdy wrzucony tam plik jest automatycznie anonimizowany bez ingerencji użytkownika.

Menu kontekstowe: Aplikacja integruje się z systemem Windows. Wystarczy kliknąć plik (.pdf, .docx, .txt) prawym przyciskiem myszy i wybrać opcję „Anonimizuj dokument”.

Inteligentne zarządzanie RAM: W trybie gotowości, gdy modele AI są załadowane w celu natychmiastowego działania, aplikacja zużywa około 1.4 GB RAM. Aby oszczędzać zasoby komputera, wprowadzono inteligentny „tryb uśpienia” – po 5 minutach bezczynności ciężkie modele sztucznej inteligencji są usuwane z pamięci, a aplikacja czeka na nowe zadania z minimalnym obciążeniem.

  Українська: Огляд Anonymous-Security-Suite
Anonymous-Security-Suite — це потужна офлайн-програма, створена для автоматичного видалення конфіденційних даних (PII) з документів. Вона працює повністю локально, не передаючи жодної інформації в інтернет, що гарантує абсолютну безпеку даних.

Ключові функції:

Глибока анонімізація: Автоматично знаходить та приховує імена, адреси, назви компаній, фінансові рахунки (IBAN) та ідентифікатори (PESEL, NIP тощо) за допомогою штучного інтелекту (spaCy, HuggingFace Transformers) та регулярних виразів.

OCR та пошук логотипів: Завдяки Tesseract OCR програма вміє читати текст зі сканованих PDF-файлів, а за допомогою OpenCV — знаходити та замальовувати логотипи компаній.

Гаряча папка (Авторежим): Фоновий процес (Watchdog) постійно моніторить вказану папку. Будь-який новий файл, який туди потрапляє, одразу ж анонімізується автоматично.

Контекстне меню: Програма зручно інтегрується в операційну систему Windows. Достатньо натиснути на файл (.pdf, .docx, .txt) правою кнопкою миші та обрати пункт "Анонімізувати".

Розумне управління ОЗП: У звичайному режимі очікування, коли моделі ШІ завантажені для миттєвої роботи, програма використовує близько 1.4 ГБ оперативної пам'яті. Але для економії ресурсів ПК передбачено "сплячий режим" — через 5 хвилин бездіяльності важкі моделі автоматично вивантажуються з пам'яті, зводячи навантаження до мінімуму до появи наступного документа.
<img width="1264" height="2836" alt="C4ASS drawio (1)" src="https://github.com/user-attachments/assets/01c3fe48-22f0-4591-aaba-f5e65c30bea1" />


<img width="828" height="705" alt="SMD drawio" src="https://github.com/user-attachments/assets/cda8a629-1555-4583-a636-df1c6ecfb5cd" />


<img width="1263" height="1186" alt="Sequence Diagram drawio" src="https://github.com/user-attachments/assets/8645717f-20de-450d-8832-edf1e9abee86" />
