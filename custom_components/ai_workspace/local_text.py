"""Short texts the integration builds itself, in every language AI Workspace ships.

Form placeholders and notes inside a reply cannot come from the translation files,
because their wording depends on what a probe found. Keep each table in step with
translations/*.json.
"""

from __future__ import annotations

LANGUAGES = ("az", "cs", "de", "en", "eo", "es", "fr", "it", "ko", "nl", "pl", "ru", "sv", "zh-Hans", "zh-Hant")


def pick(table: dict[str, object], language: str = "") -> object:
    """Exact code first (zh-Hant), then its base (de-CH → de), then English."""
    code = str(language or "").strip()
    if code in table:
        return table[code]
    lowered = code.lower()
    if lowered.startswith("zh"):
        traditional = any(tag in lowered for tag in ("hant", "-tw", "-hk", "-mo"))
        return table["zh-Hant" if traditional else "zh-Hans"]
    return table.get(lowered.split("-")[0].split("_")[0], table["en"])


# (model cannot use tools, window too small). {model}, {size}
CHAT_ONLY = {
    "en": (
        "{model} cannot use tools, so I can only chat and cannot check or change your home. "
        "Pick a model with tool support in Ollama, such as qwen2.5 or llama3.1, for that.",
        "Ollama runs {model} with a {size}-token context window, too small for the Home Assistant tools, "
        "so I can only chat. Set OLLAMA_CONTEXT_LENGTH to 16384 or more on the Ollama server and restart it.",
    ),
    "de": (
        "{model} kann keine Werkzeuge nutzen. Ich kann deshalb nur chatten und dein Zuhause weder prüfen "
        "noch steuern. Wähle dafür in Ollama ein Modell mit Werkzeug-Unterstützung, etwa qwen2.5 oder llama3.1.",
        "Ollama betreibt {model} mit einem Kontextfenster von {size} Tokens. Das ist zu klein für die "
        "Home-Assistant-Werkzeuge, deshalb kann ich nur chatten. Setze OLLAMA_CONTEXT_LENGTH auf dem "
        "Ollama-Server auf 16384 oder mehr und starte ihn neu.",
    ),
    "fr": (
        "{model} ne peut pas utiliser d’outils : je peux seulement discuter, sans vérifier ni piloter votre maison. "
        "Choisissez pour cela un modèle Ollama compatible avec les outils, comme qwen2.5 ou llama3.1.",
        "Ollama exécute {model} avec une fenêtre de contexte de {size} jetons, trop petite pour les outils "
        "Home Assistant : je peux seulement discuter. Réglez OLLAMA_CONTEXT_LENGTH sur 16384 ou plus sur le "
        "serveur Ollama, puis redémarrez-le.",
    ),
    "es": (
        "{model} no puede usar herramientas, así que solo puedo conversar y no puedo revisar ni controlar tu casa. "
        "Para eso elige en Ollama un modelo con soporte de herramientas, como qwen2.5 o llama3.1.",
        "Ollama ejecuta {model} con una ventana de contexto de {size} tokens, demasiado pequeña para las "
        "herramientas de Home Assistant, así que solo puedo conversar. Pon OLLAMA_CONTEXT_LENGTH en 16384 o más "
        "en el servidor de Ollama y reinícialo.",
    ),
    "it": (
        "{model} non può usare strumenti, quindi posso solo chattare e non posso controllare né comandare la tua casa. "
        "Per questo scegli in Ollama un modello con supporto agli strumenti, come qwen2.5 o llama3.1.",
        "Ollama esegue {model} con una finestra di contesto di {size} token, troppo piccola per gli strumenti "
        "di Home Assistant, quindi posso solo chattare. Imposta OLLAMA_CONTEXT_LENGTH a 16384 o più sul server "
        "Ollama e riavvialo.",
    ),
    "nl": (
        "{model} kan geen tools gebruiken, dus ik kan alleen chatten en je huis niet controleren of bedienen. "
        "Kies daarvoor in Ollama een model met toolondersteuning, zoals qwen2.5 of llama3.1.",
        "Ollama draait {model} met een contextvenster van {size} tokens, te klein voor de Home Assistant-tools, "
        "dus ik kan alleen chatten. Zet OLLAMA_CONTEXT_LENGTH op de Ollama-server op 16384 of meer en start hem opnieuw.",
    ),
    "pl": (
        "{model} nie potrafi używać narzędzi, więc mogę tylko rozmawiać i nie mogę sprawdzać ani sterować Twoim domem. "
        "Do tego wybierz w Ollama model obsługujący narzędzia, np. qwen2.5 lub llama3.1.",
        "Ollama uruchamia {model} z oknem kontekstu {size} tokenów, za małym dla narzędzi Home Assistant, "
        "więc mogę tylko rozmawiać. Ustaw OLLAMA_CONTEXT_LENGTH na serwerze Ollama na 16384 lub więcej i uruchom go ponownie.",
    ),
    "cs": (
        "{model} neumí používat nástroje, takže můžu jen chatovat a nemůžu kontrolovat ani ovládat vaši domácnost. "
        "Pro to zvolte v Ollamě model s podporou nástrojů, například qwen2.5 nebo llama3.1.",
        "Ollama spouští {model} s kontextovým oknem {size} tokenů, které je pro nástroje Home Assistantu příliš "
        "malé, takže můžu jen chatovat. Nastavte na serveru Ollama OLLAMA_CONTEXT_LENGTH na 16384 nebo více a restartujte ho.",
    ),
    "sv": (
        "{model} kan inte använda verktyg, så jag kan bara chatta och inte kontrollera eller styra ditt hem. "
        "Välj för det en modell med verktygsstöd i Ollama, till exempel qwen2.5 eller llama3.1.",
        "Ollama kör {model} med ett kontextfönster på {size} tokens, för litet för Home Assistant-verktygen, "
        "så jag kan bara chatta. Sätt OLLAMA_CONTEXT_LENGTH till 16384 eller mer på Ollama-servern och starta om den.",
    ),
    "ru": (
        "{model} не умеет пользоваться инструментами, поэтому я могу только общаться и не могу проверять или "
        "управлять вашим домом. Для этого выберите в Ollama модель с поддержкой инструментов, например qwen2.5 или llama3.1.",
        "Ollama запускает {model} с контекстным окном {size} токенов — это слишком мало для инструментов "
        "Home Assistant, поэтому я могу только общаться. Установите OLLAMA_CONTEXT_LENGTH на сервере Ollama "
        "в 16384 или больше и перезапустите его.",
    ),
    "ko": (
        "{model}은(는) 도구를 사용할 수 없어서 대화만 할 수 있고 집을 확인하거나 제어할 수 없습니다. "
        "그러려면 Ollama에서 qwen2.5나 llama3.1처럼 도구를 지원하는 모델을 선택하세요.",
        "Ollama가 {model}을(를) {size}토큰 컨텍스트 창으로 실행하고 있어 Home Assistant 도구에는 너무 작으므로 "
        "대화만 할 수 있습니다. Ollama 서버에서 OLLAMA_CONTEXT_LENGTH를 16384 이상으로 설정하고 다시 시작하세요.",
    ),
    "zh-Hans": (
        "{model} 无法使用工具，所以我只能聊天，不能查看或控制你的家。"
        "如需这些功能，请在 Ollama 中选择支持工具的模型，例如 qwen2.5 或 llama3.1。",
        "Ollama 以 {size} 个令牌的上下文窗口运行 {model}，对 Home Assistant 工具来说太小，所以我只能聊天。"
        "请在 Ollama 服务器上将 OLLAMA_CONTEXT_LENGTH 设为 16384 或更大，然后重启。",
    ),
    "zh-Hant": (
        "{model} 無法使用工具，所以我只能聊天，不能查看或控制你的家。"
        "如需這些功能，請在 Ollama 中選擇支援工具的模型，例如 qwen2.5 或 llama3.1。",
        "Ollama 以 {size} 個權杖的上下文視窗執行 {model}，對 Home Assistant 工具來說太小，所以我只能聊天。"
        "請在 Ollama 伺服器上將 OLLAMA_CONTEXT_LENGTH 設為 16384 或更大，然後重新啟動。",
    ),
    "az": (
        "{model} alətlərdən istifadə edə bilmir, ona görə yalnız söhbət edə bilərəm, evinizi yoxlaya və ya idarə edə bilmərəm. "
        "Bunun üçün Ollama-da alətləri dəstəkləyən model seçin, məsələn qwen2.5 və ya llama3.1.",
        "Ollama {model} modelini {size} tokenlik kontekst pəncərəsi ilə işlədir, bu Home Assistant alətləri üçün "
        "çox kiçikdir, ona görə yalnız söhbət edə bilərəm. Ollama serverində OLLAMA_CONTEXT_LENGTH dəyərini 16384 "
        "və ya daha çox edin və serveri yenidən başladın.",
    ),
    "eo": (
        "{model} ne povas uzi ilojn, do mi povas nur babili kaj ne povas kontroli aŭ stiri vian hejmon. "
        "Por tio elektu en Ollama modelon kun ila subteno, ekzemple qwen2.5 aŭ llama3.1.",
        "Ollama rulas {model} kun kunteksta fenestro de {size} ĵetonoj, tro malgranda por la iloj de Home Assistant, "
        "do mi povas nur babili. Agordu OLLAMA_CONTEXT_LENGTH al 16384 aŭ pli en la Ollama-servilo kaj rekomencu ĝin.",
    ),
}

# (found, not found). {version}, {models}, {example}
OLLAMA_FORM = {
    "en": ("✅ Ollama {version} found, {models} model(s) installed.", "⚠️ No Ollama answers at this address. Usually {example}"),
    "de": ("✅ Ollama {version} gefunden, {models} Modell(e) installiert.", "⚠️ Unter dieser Adresse antwortet kein Ollama. Meist {example}"),
    "fr": ("✅ Ollama {version} trouvé, {models} modèle(s) installé(s).", "⚠️ Aucun Ollama ne répond à cette adresse. Généralement {example}"),
    "es": ("✅ Ollama {version} encontrado, {models} modelo(s) instalado(s).", "⚠️ Ningún Ollama responde en esta dirección. Normalmente {example}"),
    "it": ("✅ Ollama {version} trovato, {models} modello/i installato/i.", "⚠️ Nessun Ollama risponde a questo indirizzo. Di solito {example}"),
    "nl": ("✅ Ollama {version} gevonden, {models} model(len) geïnstalleerd.", "⚠️ Op dit adres antwoordt geen Ollama. Meestal {example}"),
    "pl": ("✅ Znaleziono Ollama {version}, zainstalowane modele: {models}.", "⚠️ Pod tym adresem nie odpowiada żadna Ollama. Zwykle {example}"),
    "cs": ("✅ Nalezena Ollama {version}, nainstalované modely: {models}.", "⚠️ Na této adrese neodpovídá žádná Ollama. Obvykle {example}"),
    "sv": ("✅ Ollama {version} hittades, {models} modell(er) installerade.", "⚠️ Ingen Ollama svarar på den här adressen. Vanligtvis {example}"),
    "ru": ("✅ Найдена Ollama {version}, установлено моделей: {models}.", "⚠️ По этому адресу Ollama не отвечает. Обычно {example}"),
    "ko": ("✅ Ollama {version} 발견, 설치된 모델 {models}개.", "⚠️ 이 주소에서 응답하는 Ollama가 없습니다. 보통 {example}"),
    "zh-Hans": ("✅ 已找到 Ollama {version}，已安装 {models} 个模型。", "⚠️ 此地址没有 Ollama 响应。通常是 {example}"),
    "zh-Hant": ("✅ 已找到 Ollama {version}，已安裝 {models} 個模型。", "⚠️ 此位址沒有 Ollama 回應。通常是 {example}"),
    "az": ("✅ Ollama {version} tapıldı, quraşdırılmış modellər: {models}.", "⚠️ Bu ünvanda Ollama cavab vermir. Adətən {example}"),
    "eo": ("✅ Ollama {version} trovita, instalitaj modeloj: {models}.", "⚠️ Neniu Ollama respondas ĉe ĉi tiu adreso. Kutime {example}"),
}

# (found, detected but not answering yet, hint, " · auto-detected" mark)
RUNTIME_FORM = {
    "en": ("✅ Runtime found.", "We found your AI Workspace Runtime on this system.", "Address of your AI Workspace Runtime, as seen from Home Assistant. Leave empty to auto-detect when the runtime is reachable.", " · auto-detected"),
    "de": ("✅ Runtime gefunden.", "Deine AI-Workspace-Runtime wurde auf diesem System gefunden.", "Adresse deiner AI-Workspace-Runtime aus Sicht von Home Assistant. Leer lassen, um sie automatisch zu finden, sobald sie erreichbar ist.", " · automatisch erkannt"),
    "fr": ("✅ Runtime trouvé.", "Votre AI Workspace Runtime a été trouvé sur ce système.", "Adresse de votre AI Workspace Runtime, vue depuis Home Assistant. Laissez vide pour la détecter automatiquement quand le runtime est joignable.", " · détecté automatiquement"),
    "es": ("✅ Runtime encontrado.", "Encontramos tu AI Workspace Runtime en este sistema.", "Dirección de tu AI Workspace Runtime, vista desde Home Assistant. Déjala vacía para detectarla automáticamente cuando el runtime esté disponible.", " · detectado automáticamente"),
    "it": ("✅ Runtime trovato.", "Abbiamo trovato il tuo AI Workspace Runtime su questo sistema.", "Indirizzo del tuo AI Workspace Runtime, visto da Home Assistant. Lascia vuoto per rilevarlo automaticamente quando il runtime è raggiungibile.", " · rilevato automaticamente"),
    "nl": ("✅ Runtime gevonden.", "Je AI Workspace Runtime is op dit systeem gevonden.", "Adres van je AI Workspace Runtime, gezien vanuit Home Assistant. Laat leeg om het automatisch te vinden zodra de runtime bereikbaar is.", " · automatisch gevonden"),
    "pl": ("✅ Znaleziono runtime.", "Znaleźliśmy Twój AI Workspace Runtime w tym systemie.", "Adres Twojego AI Workspace Runtime widziany z Home Assistant. Zostaw puste, aby wykryć go automatycznie, gdy runtime będzie dostępny.", " · wykryto automatycznie"),
    "cs": ("✅ Runtime nalezen.", "Na tomto systému jsme našli váš AI Workspace Runtime.", "Adresa vašeho AI Workspace Runtime z pohledu Home Assistantu. Nechte prázdné pro automatické zjištění, jakmile bude runtime dostupný.", " · zjištěno automaticky"),
    "sv": ("✅ Runtime hittades.", "Vi hittade din AI Workspace Runtime på det här systemet.", "Adress till din AI Workspace Runtime, sett från Home Assistant. Lämna tomt för att hitta den automatiskt när runtime är nåbar.", " · hittades automatiskt"),
    "ru": ("✅ Среда выполнения найдена.", "Ваш AI Workspace Runtime найден в этой системе.", "Адрес вашего AI Workspace Runtime с точки зрения Home Assistant. Оставьте пустым, чтобы найти его автоматически, когда он будет доступен.", " · найдено автоматически"),
    "ko": ("✅ 런타임을 찾았습니다.", "이 시스템에서 AI Workspace Runtime을 찾았습니다.", "Home Assistant에서 본 AI Workspace Runtime 주소입니다. 런타임에 연결할 수 있을 때 자동으로 찾으려면 비워 두세요.", " · 자동 감지됨"),
    "zh-Hans": ("✅ 已找到运行时。", "已在此系统上找到你的 AI Workspace Runtime。", "从 Home Assistant 看到的 AI Workspace Runtime 地址。留空则在运行时可访问时自动检测。", " · 自动检测"),
    "zh-Hant": ("✅ 已找到執行環境。", "已在此系統上找到你的 AI Workspace Runtime。", "從 Home Assistant 看到的 AI Workspace Runtime 位址。留空則在執行環境可連線時自動偵測。", " · 自動偵測"),
    "az": ("✅ Runtime tapıldı.", "AI Workspace Runtime bu sistemdə tapıldı.", "Home Assistant-dan görünən AI Workspace Runtime ünvanı. Runtime əlçatan olanda avtomatik tapmaq üçün boş saxlayın.", " · avtomatik tapıldı"),
    "eo": ("✅ Rultempo trovita.", "Ni trovis vian AI Workspace Runtime en ĉi tiu sistemo.", "Adreso de via AI Workspace Runtime, vidata el Home Assistant. Lasu malplena por aŭtomate trovi ĝin, kiam la rultempo estas atingebla.", " · aŭtomate trovita"),
}


# Claude sign-in state on the agent form (Claude SDK on the Runtime). {saved}, {expires}, {kind}
# "overridden" only comes from Runtimes before 1.6.0b12: since then a sign-in wins over the Runtime's own token.
CLAUDE_SIGNIN = {
    "en": {
        "signed_in": "✅ Signed in with your Claude plan on the Runtime (since {saved}, valid until about {expires}).",
        "settings": "✅ The Runtime has its own Claude credential ({kind}), from its environment (Docker) or an older App option. Signing in here takes over from it.",
        "none": "⚠️ Not signed in yet. Sign in with your Claude plan, or go back and paste a token.",
        "overridden": "Note: this Runtime version still lets a Plan token in its options or environment win over your sign-in. Update the AI Workspace Runtime so the sign-in wins.",
        "own_key": "This agent has its own token or key, which wins over the Runtime's credential. Signing in removes it from this agent.",
        "old": "This Runtime cannot sign in yet. Update the AI Workspace Runtime, or go back and paste a token.",
        "unreachable": "The Runtime did not answer, so the sign-in state is unknown.",
    },
    "de": {
        "signed_in": "✅ Auf der Runtime mit deinem Claude-Abo angemeldet (seit {saved}, gültig bis etwa {expires}).",
        "settings": "✅ Die Runtime hat einen eigenen Claude-Zugang ({kind}), aus ihrer Umgebung (Docker) oder einer älteren App-Option. Eine Anmeldung hier löst ihn ab.",
        "none": "⚠️ Noch nicht angemeldet. Melde dich mit deinem Claude-Abo an oder geh zurück und füge ein Token ein.",
        "overridden": "Hinweis: Bei dieser Runtime-Version hat ein Plan-Token in ihren Optionen oder ihrer Umgebung noch Vorrang vor deiner Anmeldung. Aktualisiere die AI-Workspace-Runtime, dann gilt die Anmeldung.",
        "own_key": "Dieser Agent hat ein eigenes Token oder einen eigenen Schlüssel, der Vorrang vor dem Zugang der Runtime hat. Die Anmeldung entfernt es von diesem Agenten.",
        "old": "Diese Runtime kann sich noch nicht anmelden. Aktualisiere die AI-Workspace-Runtime oder geh zurück und füge ein Token ein.",
        "unreachable": "Die Runtime hat nicht geantwortet, der Anmeldestatus ist unbekannt.",
    },
    "fr": {
        "signed_in": "✅ Connecté avec votre abonnement Claude sur le Runtime (depuis le {saved}, valable jusqu'au {expires} environ).",
        "settings": "✅ Le Runtime a son propre identifiant Claude ({kind}), venant de son environnement (Docker) ou d'une ancienne option de l'App. Une connexion ici le remplace.",
        "none": "⚠️ Pas encore connecté. Connectez-vous avec votre abonnement Claude, ou revenez en arrière et collez un jeton.",
        "overridden": "Remarque : avec cette version du Runtime, un jeton Plan dans ses options ou son environnement l'emporte encore sur votre connexion. Mettez à jour AI Workspace Runtime pour que la connexion l'emporte.",
        "own_key": "Cet agent a son propre jeton ou sa propre clé, qui l'emporte sur l'identifiant du Runtime. La connexion le retire de cet agent.",
        "old": "Ce Runtime ne sait pas encore se connecter. Mettez à jour AI Workspace Runtime, ou revenez en arrière et collez un jeton.",
        "unreachable": "Le Runtime n'a pas répondu, l'état de connexion est inconnu.",
    },
    "es": {
        "signed_in": "✅ Sesión iniciada con tu plan de Claude en el Runtime (desde {saved}, válida hasta aprox. {expires}).",
        "settings": "✅ El Runtime tiene su propia credencial de Claude ({kind}), de su entorno (Docker) o de una opción antigua de la App. Iniciar sesión aquí la sustituye.",
        "none": "⚠️ Aún sin sesión. Inicia sesión con tu plan de Claude, o vuelve atrás y pega un token.",
        "overridden": "Nota: en esta versión del Runtime, un token Plan en sus opciones o su entorno todavía tiene prioridad sobre tu sesión. Actualiza AI Workspace Runtime para que gane la sesión.",
        "own_key": "Este agente tiene su propio token o clave, que tiene prioridad sobre la credencial del Runtime. Al iniciar sesión se quita de este agente.",
        "old": "Este Runtime aún no puede iniciar sesión. Actualiza AI Workspace Runtime, o vuelve atrás y pega un token.",
        "unreachable": "El Runtime no respondió, así que no se sabe el estado de la sesión.",
    },
    "it": {
        "signed_in": "✅ Accesso effettuato con il tuo piano Claude sul Runtime (dal {saved}, valido fino a circa {expires}).",
        "settings": "✅ Il Runtime ha una propria credenziale Claude ({kind}), dal suo ambiente (Docker) o da una vecchia opzione dell'App. Accedere qui la sostituisce.",
        "none": "⚠️ Accesso non ancora effettuato. Accedi con il tuo piano Claude, oppure torna indietro e incolla un token.",
        "overridden": "Nota: con questa versione del Runtime un token Plan nelle sue opzioni o nel suo ambiente ha ancora la precedenza sul tuo accesso. Aggiorna AI Workspace Runtime perché valga l'accesso.",
        "own_key": "Questo agente ha un proprio token o chiave, che ha la precedenza sulla credenziale del Runtime. L'accesso lo rimuove da questo agente.",
        "old": "Questo Runtime non supporta ancora l'accesso. Aggiorna AI Workspace Runtime, oppure torna indietro e incolla un token.",
        "unreachable": "Il Runtime non ha risposto, lo stato di accesso è sconosciuto.",
    },
    "nl": {
        "signed_in": "✅ Aangemeld met je Claude-abonnement op de Runtime (sinds {saved}, geldig tot ongeveer {expires}).",
        "settings": "✅ De Runtime heeft een eigen Claude-toegang ({kind}), uit zijn omgeving (Docker) of een oudere App-optie. Hier aanmelden neemt die over.",
        "none": "⚠️ Nog niet aangemeld. Meld je aan met je Claude-abonnement, of ga terug en plak een token.",
        "overridden": "Let op: bij deze Runtime-versie gaat een Plan-token in de opties of omgeving nog voor op je aanmelding. Werk de AI Workspace Runtime bij zodat de aanmelding voorgaat.",
        "own_key": "Deze agent heeft een eigen token of sleutel, die voorgaat op de toegang van de Runtime. Aanmelden verwijdert die van deze agent.",
        "old": "Deze Runtime kan nog niet aanmelden. Werk de AI Workspace Runtime bij, of ga terug en plak een token.",
        "unreachable": "De Runtime antwoordde niet, de aanmeldstatus is onbekend.",
    },
    "pl": {
        "signed_in": "✅ Zalogowano planem Claude w Runtime (od {saved}, ważne do ok. {expires}).",
        "settings": "✅ Runtime ma własne dane logowania Claude ({kind}) ze swojego środowiska (Docker) lub ze starszej opcji aplikacji. Zalogowanie się tutaj je zastępuje.",
        "none": "⚠️ Jeszcze nie zalogowano. Zaloguj się planem Claude albo wróć i wklej token.",
        "overridden": "Uwaga: w tej wersji Runtime token Plan w opcjach lub środowisku nadal ma pierwszeństwo przed Twoim logowaniem. Zaktualizuj AI Workspace Runtime, aby liczyło się logowanie.",
        "own_key": "Ten agent ma własny token lub klucz, który ma pierwszeństwo przed danymi Runtime. Zalogowanie usuwa go z tego agenta.",
        "old": "Ten Runtime nie obsługuje jeszcze logowania. Zaktualizuj AI Workspace Runtime albo wróć i wklej token.",
        "unreachable": "Runtime nie odpowiedział, stan logowania jest nieznany.",
    },
    "cs": {
        "signed_in": "✅ Přihlášeno předplatným Claude na Runtime (od {saved}, platné přibližně do {expires}).",
        "settings": "✅ Runtime má vlastní přístup ke Claude ({kind}) ze svého prostředí (Docker) nebo ze starší volby aplikace. Přihlášení zde jej nahradí.",
        "none": "⚠️ Zatím nepřihlášeno. Přihlaste se předplatným Claude, nebo se vraťte a vložte token.",
        "overridden": "Pozor: u této verze Runtime má token Plan ve volbách nebo prostředí stále přednost před vaším přihlášením. Aktualizujte AI Workspace Runtime, aby platilo přihlášení.",
        "own_key": "Tento agent má vlastní token nebo klíč, který má přednost před přístupem Runtime. Přihlášení jej z agenta odebere.",
        "old": "Tento Runtime se zatím neumí přihlásit. Aktualizujte AI Workspace Runtime, nebo se vraťte a vložte token.",
        "unreachable": "Runtime neodpověděl, stav přihlášení není znám.",
    },
    "sv": {
        "signed_in": "✅ Inloggad med din Claude-plan på Runtime (sedan {saved}, giltig till ungefär {expires}).",
        "settings": "✅ Runtime har en egen Claude-inloggning ({kind}) från sin miljö (Docker) eller ett äldre App-alternativ. Att logga in här tar över efter den.",
        "none": "⚠️ Inte inloggad än. Logga in med din Claude-plan, eller gå tillbaka och klistra in en token.",
        "overridden": "Obs: i den här Runtime-versionen går en Plan-token i alternativen eller miljön fortfarande före din inloggning. Uppdatera AI Workspace Runtime så att inloggningen gäller.",
        "own_key": "Den här agenten har en egen token eller nyckel, som går före Runtimes inloggning. Inloggningen tar bort den från agenten.",
        "old": "Den här Runtime kan inte logga in än. Uppdatera AI Workspace Runtime, eller gå tillbaka och klistra in en token.",
        "unreachable": "Runtime svarade inte, så inloggningsstatus är okänd.",
    },
    "ru": {
        "signed_in": "✅ Выполнен вход с подпиской Claude в Runtime (с {saved}, действует примерно до {expires}).",
        "settings": "✅ У Runtime есть собственные учётные данные Claude ({kind}) из окружения (Docker) или из старой настройки приложения. Вход здесь их заменяет.",
        "none": "⚠️ Вход ещё не выполнен. Войдите с подпиской Claude или вернитесь назад и вставьте токен.",
        "overridden": "Внимание: в этой версии Runtime токен Plan в настройках или окружении всё ещё важнее вашего входа. Обновите AI Workspace Runtime, чтобы действовал вход.",
        "own_key": "У этого агента свой токен или ключ, он важнее учётных данных Runtime. Вход удалит его у этого агента.",
        "old": "Этот Runtime пока не умеет входить. Обновите AI Workspace Runtime или вернитесь назад и вставьте токен.",
        "unreachable": "Runtime не ответил, состояние входа неизвестно.",
    },
    "ko": {
        "signed_in": "✅ 런타임에서 Claude 요금제로 로그인했습니다 ({saved}부터, 약 {expires}까지 유효).",
        "settings": "✅ 런타임에 환경(Docker) 또는 이전 앱 옵션에서 온 자체 Claude 자격 증명({kind})이 있습니다. 여기서 로그인하면 그것을 대신합니다.",
        "none": "⚠️ 아직 로그인하지 않았습니다. Claude 요금제로 로그인하거나, 돌아가서 토큰을 붙여 넣으세요.",
        "overridden": "참고: 이 런타임 버전에서는 옵션이나 환경의 Plan 토큰이 여전히 로그인보다 우선합니다. 로그인이 우선하도록 AI Workspace Runtime을 업데이트하세요.",
        "own_key": "이 에이전트에는 런타임 자격 증명보다 우선하는 자체 토큰이나 키가 있습니다. 로그인하면 이 에이전트에서 제거됩니다.",
        "old": "이 런타임은 아직 로그인을 지원하지 않습니다. AI Workspace Runtime을 업데이트하거나, 돌아가서 토큰을 붙여 넣으세요.",
        "unreachable": "런타임이 응답하지 않아 로그인 상태를 알 수 없습니다.",
    },
    "zh-Hans": {
        "signed_in": "✅ 已在运行时上用你的 Claude 订阅登录（自 {saved} 起，约有效至 {expires}）。",
        "settings": "✅ 运行时有自己的 Claude 凭据（{kind}），来自其环境（Docker）或旧版应用选项。在此登录将取而代之。",
        "none": "⚠️ 尚未登录。请用你的 Claude 订阅登录，或返回并粘贴令牌。",
        "overridden": "注意：此版本的运行时中，其选项或环境里的 Plan 令牌仍优先于你的登录。请更新 AI Workspace Runtime，让登录生效。",
        "own_key": "此代理有自己的令牌或密钥，优先于运行时的凭据。登录后会从此代理中移除。",
        "old": "此运行时尚不支持登录。请更新 AI Workspace Runtime，或返回并粘贴令牌。",
        "unreachable": "运行时没有响应，登录状态未知。",
    },
    "zh-Hant": {
        "signed_in": "✅ 已在執行環境上用你的 Claude 訂閱登入（自 {saved} 起，約有效至 {expires}）。",
        "settings": "✅ 執行環境有自己的 Claude 憑證（{kind}），來自其環境（Docker）或舊版應用程式選項。在此登入將取而代之。",
        "none": "⚠️ 尚未登入。請用你的 Claude 訂閱登入，或返回並貼上權杖。",
        "overridden": "注意：此版本的執行環境中，其選項或環境裡的 Plan 權杖仍優先於你的登入。請更新 AI Workspace Runtime，讓登入生效。",
        "own_key": "此代理有自己的權杖或金鑰，優先於執行環境的憑證。登入後會從此代理移除。",
        "old": "此執行環境尚不支援登入。請更新 AI Workspace Runtime，或返回並貼上權杖。",
        "unreachable": "執行環境沒有回應，登入狀態未知。",
    },
    "az": {
        "signed_in": "✅ Runtime-da Claude planınızla daxil olunub ({saved} tarixindən, təxminən {expires} tarixinədək etibarlıdır).",
        "settings": "✅ Runtime-ın öz mühitindən (Docker) və ya köhnə App seçimindən gələn öz Claude giriş məlumatı var ({kind}). Burada daxil olmaq onu əvəz edir.",
        "none": "⚠️ Hələ daxil olunmayıb. Claude planınızla daxil olun və ya geri qayıdıb token yapışdırın.",
        "overridden": "Qeyd: bu Runtime versiyasında seçimlərdəki və ya mühitdəki Plan tokeni hələ də girişinizdən üstündür. Girişin keçərli olması üçün AI Workspace Runtime-ı yeniləyin.",
        "own_key": "Bu agentin öz tokeni və ya açarı var və o, Runtime məlumatından üstündür. Daxil olmaq onu bu agentdən silir.",
        "old": "Bu Runtime hələ daxil ola bilmir. AI Workspace Runtime-ı yeniləyin və ya geri qayıdıb token yapışdırın.",
        "unreachable": "Runtime cavab vermədi, giriş vəziyyəti məlum deyil.",
    },
    "eo": {
        "signed_in": "✅ Ensalutinta per via Claude-abono ĉe la rultempo (ekde {saved}, valida ĝis ĉirkaŭ {expires}).",
        "settings": "✅ La rultempo havas propran Claude-akreditaĵon ({kind}), el sia medio (Docker) aŭ malnova agordo de la App. Ensaluto ĉi tie anstataŭas ĝin.",
        "none": "⚠️ Ankoraŭ ne ensalutinta. Ensalutu per via Claude-abono, aŭ reiru kaj algluu ĵetonon.",
        "overridden": "Rimarko: ĉe ĉi tiu versio de la rultempo Plan-ĵetono en ĝiaj agordoj aŭ medio ankoraŭ superas vian ensaluton. Ĝisdatigu AI Workspace Runtime por ke la ensaluto validu.",
        "own_key": "Ĉi tiu agento havas propran ĵetonon aŭ ŝlosilon, kiu superas la akreditaĵon de la rultempo. Ensaluto forigas ĝin de ĉi tiu agento.",
        "old": "Ĉi tiu rultempo ankoraŭ ne povas ensaluti. Ĝisdatigu AI Workspace Runtime, aŭ reiru kaj algluu ĵetonon.",
        "unreachable": "La rultempo ne respondis, do la ensaluta stato estas nekonata.",
    },
}

_CLAUDE_KIND = {"plan": "Claude Plan", "api": "Anthropic API"}


def claude_signin_text(status: dict | None, own_key: bool, language: str = "", problem: str = "") -> str:
    """One or two sentences for the agent form: is the Runtime signed in, and what wins."""
    words = pick(CLAUDE_SIGNIN, language)
    lines: list[str] = []
    if problem == "runtime_old":
        lines.append(words["old"])
    elif problem or status is None:
        lines.append(words["unreachable"])
    else:
        signed = status.get("signed_in") or None
        source = str(status.get("credential") or "none")
        if source == "signed-in" and isinstance(signed, dict):
            lines.append(
                words["signed_in"].format(
                    saved=str(signed.get("saved_at") or "")[:10] or "?",
                    expires=str(signed.get("expires_at") or "")[:10] or "?",
                )
            )
        elif source == "settings":
            kind = _CLAUDE_KIND.get(str(status.get("kind") or ""), "Claude")
            lines.append(words["settings"].format(kind=kind))
            if status.get("overridden"):
                lines.append(words["overridden"])
        else:
            lines.append(words["none"])
    if own_key:
        lines.append(words["own_key"])
    return "\n\n".join(lines)


CODEX_SIGNIN = {
    "en": {
        "old": "⚠️ This Runtime is too old for OpenAI Codex. Update the AI Workspace Runtime (App or Docker image) to 1.6.0 or newer.",
        "unreachable": "⚠️ The Runtime did not answer. Check the Runtime address and password on the previous page.",
        "signed_in": "✅ Signed in with ChatGPT on the Runtime{plan} (since {saved}). Every Codex agent on this Runtime without its own key uses it.",
        "api_key": "✅ The Runtime has an OpenAI API key for Codex (billed as API usage).",
        "none": "⚠️ Not signed in yet. Pick **Sign in with ChatGPT**, or go back and paste an OpenAI API key.",
        "own_key": "This agent uses its own OpenAI API key; it wins over the Runtime's sign-in.",
    },
    "de": {
        "old": "⚠️ Diese Runtime ist zu alt für OpenAI Codex. Aktualisiere die AI-Workspace-Runtime (App oder Docker-Image) auf 1.6.0 oder neuer.",
        "unreachable": "⚠️ Die Runtime hat nicht geantwortet. Prüfe Runtime-Adresse und Passwort auf der vorigen Seite.",
        "signed_in": "✅ Auf der Runtime mit ChatGPT angemeldet{plan} (seit {saved}). Jeder Codex-Agent auf dieser Runtime ohne eigenen Schlüssel nutzt das.",
        "api_key": "✅ Die Runtime hat einen OpenAI-API-Schlüssel für Codex (abgerechnet als API-Nutzung).",
        "none": "⚠️ Noch nicht angemeldet. Wähle **Mit ChatGPT anmelden** oder geh zurück und füge einen OpenAI-API-Schlüssel ein.",
        "own_key": "Dieser Agent nutzt seinen eigenen OpenAI-API-Schlüssel; er hat Vorrang vor der Anmeldung der Runtime.",
    },
}


def codex_signin_text(status: dict | None, own_key: bool, language: str = "", problem: str = "") -> str:
    """For the Codex account step: is the Runtime signed in with ChatGPT, and what wins."""
    words = CODEX_SIGNIN.get((language or "en").split("-")[0], CODEX_SIGNIN["en"])
    lines: list[str] = []
    if problem == "runtime_old":
        lines.append(words["old"])
    elif problem or status is None:
        lines.append(words["unreachable"])
    else:
        signed = status.get("signed_in") if isinstance(status.get("signed_in"), dict) else None
        if signed and signed.get("mode") == "chatgpt":
            plan = str(signed.get("plan") or "").strip()
            lines.append(
                words["signed_in"].format(
                    plan=f" ({plan.title()})" if plan else "", saved=str(signed.get("saved_at") or "")[:10] or "?"
                )
            )
        elif status.get("ready"):
            lines.append(words["api_key"])
        else:
            lines.append(words["none"])
    if own_key:
        lines.append(words["own_key"])
    return "\n\n".join(lines)


# Chat error when Anthropic refuses the Claude credential (Runtime error code claude_auth_failed).
CLAUDE_AUTH_FAILED_CODE = "claude_auth_failed"
CLAUDE_AUTH_FAILED = {
    "en": "Claude no longer accepts this sign-in or key: it has expired or was revoked. Open this agent's settings (Settings → Devices & services → AI Workspace) and sign in with Claude again, or replace the token or API key.",
    "de": "Claude akzeptiert diese Anmeldung oder diesen Schlüssel nicht mehr: abgelaufen oder widerrufen. Öffne die Einstellungen dieses Agenten (Einstellungen → Geräte & Dienste → AI Workspace) und melde dich erneut mit Claude an, oder ersetze das Token bzw. den API-Schlüssel.",
    "fr": "Claude n'accepte plus cette connexion ou cette clé : elle a expiré ou a été révoquée. Ouvrez les réglages de cet agent (Paramètres → Appareils et services → AI Workspace) et reconnectez-vous avec Claude, ou remplacez le jeton ou la clé API.",
    "es": "Claude ya no acepta este inicio de sesión o clave: ha caducado o fue revocado. Abre los ajustes de este agente (Ajustes → Dispositivos y servicios → AI Workspace) e inicia sesión con Claude de nuevo, o sustituye el token o la clave API.",
    "it": "Claude non accetta più questo accesso o questa chiave: è scaduto o è stato revocato. Apri le impostazioni di questo agente (Impostazioni → Dispositivi e servizi → AI Workspace) e accedi di nuovo con Claude, oppure sostituisci il token o la chiave API.",
    "nl": "Claude accepteert deze aanmelding of sleutel niet meer: verlopen of ingetrokken. Open de instellingen van deze agent (Instellingen → Apparaten & diensten → AI Workspace) en meld je opnieuw aan met Claude, of vervang het token of de API-sleutel.",
    "pl": "Claude nie akceptuje już tego logowania lub klucza: wygasło lub zostało unieważnione. Otwórz ustawienia tego agenta (Ustawienia → Urządzenia i usługi → AI Workspace) i zaloguj się ponownie przez Claude albo zastąp token lub klucz API.",
    "cs": "Claude už toto přihlášení nebo klíč nepřijímá: vypršel nebo byl odvolán. Otevřete nastavení tohoto agenta (Nastavení → Zařízení a služby → AI Workspace) a znovu se přihlaste přes Claude, nebo nahraďte token či klíč API.",
    "sv": "Claude godtar inte längre den här inloggningen eller nyckeln: den har gått ut eller återkallats. Öppna agentens inställningar (Inställningar → Enheter och tjänster → AI Workspace) och logga in med Claude igen, eller byt token eller API-nyckel.",
    "ru": "Claude больше не принимает этот вход или ключ: срок действия истёк или он отозван. Откройте настройки этого агента (Настройки → Устройства и службы → AI Workspace) и войдите через Claude снова или замените токен или ключ API.",
    "ko": "Claude가 더 이상 이 로그인 또는 키를 받아들이지 않습니다. 만료되었거나 취소되었습니다. 이 에이전트의 설정(설정 → 기기 및 서비스 → AI Workspace)을 열고 Claude로 다시 로그인하거나 토큰 또는 API 키를 바꾸세요.",
    "zh-Hans": "Claude 不再接受此登录或密钥：已过期或已被撤销。请打开此代理的设置（设置 → 设备与服务 → AI Workspace），重新用 Claude 登录，或更换令牌或 API 密钥。",
    "zh-Hant": "Claude 不再接受此登入或金鑰：已過期或已被撤銷。請開啟此代理的設定（設定 → 裝置與服務 → AI Workspace），重新用 Claude 登入，或更換權杖或 API 金鑰。",
    "az": "Claude artıq bu girişi və ya açarı qəbul etmir: vaxtı bitib və ya ləğv edilib. Bu agentin ayarlarını açın (Ayarlar → Cihazlar və xidmətlər → AI Workspace) və Claude ilə yenidən daxil olun, ya da tokeni və ya API açarını dəyişin.",
    "eo": "Claude ne plu akceptas ĉi tiun ensaluton aŭ ŝlosilon: ĝi eksvalidiĝis aŭ estis revokita. Malfermu la agordojn de ĉi tiu agento (Agordoj → Aparatoj kaj servoj → AI Workspace) kaj ensalutu per Claude denove, aŭ anstataŭigu la ĵetonon aŭ API-ŝlosilon.",
}


def claude_auth_failed_text(language: str = "") -> str:
    """Sign in with Claude again: the expired or revoked sign-in / key, in the chat's language."""
    return str(pick(CLAUDE_AUTH_FAILED, language))


CLAUDE_PLAN_REJECTED_SESSION = {
    "en": "Claude session is full. Continue from {reset}.",
    "de": "Claude-Sitzung ist voll. Weiter ab {reset}.",
    "fr": "La session Claude est pleine. Reprenez à partir de {reset}.",
    "es": "La sesión de Claude está llena. Continúe a partir de las {reset}.",
}
CLAUDE_PLAN_REJECTED_WEEK = {
    "en": "Claude weekly limit is full. Continue from {reset}.",
    "de": "Claude-Wochenlimit ist voll. Weiter ab {reset}.",
    "fr": "La limite hebdomadaire Claude est atteinte. Reprenez à partir de {reset}.",
    "es": "El límite semanal de Claude está lleno. Continúe a partir de las {reset}.",
}


def claude_plan_rejected_text(language: str = "", *, window: str = "session", reset: str = "?") -> str:
    table = CLAUDE_PLAN_REJECTED_WEEK if str(window or "") == "week" else CLAUDE_PLAN_REJECTED_SESSION
    return str(pick(table, language)).format(reset=reset or "?")


# Under the Cursor key field when the Runtime already has its own Cursor key.
CURSOR_KEY_NOTE = {
    "en": "✅ The Runtime already has a Cursor key. Leave this empty to use it.",
    "de": "✅ Die Runtime hat schon einen Cursor-Schlüssel. Leer lassen, um ihn zu nutzen.",
    "az": "✅ Runtime-da artıq Cursor açarı var. Ondan istifadə etmək üçün boş buraxın.",
    "cs": "✅ Runtime už má klíč Cursor. Nechte pole prázdné a použije se.",
    "eo": "✅ La Runtime jam havas Cursor-ŝlosilon. Lasu ĉi tion malplena por uzi ĝin.",
    "es": "✅ El Runtime ya tiene una clave de Cursor. Déjalo vacío para usarla.",
    "fr": "✅ Le Runtime a déjà une clé Cursor. Laissez ce champ vide pour l’utiliser.",
    "it": "✅ Il Runtime ha già una chiave Cursor. Lascia vuoto per usarla.",
    "ko": "✅ 런타임에 이미 Cursor 키가 있습니다. 그 키를 쓰려면 비워 두세요.",
    "nl": "✅ De Runtime heeft al een Cursor-sleutel. Laat dit leeg om die te gebruiken.",
    "pl": "✅ Runtime ma już klucz Cursor. Zostaw puste, aby go użyć.",
    "ru": "✅ У Runtime уже есть ключ Cursor. Оставьте поле пустым, чтобы использовать его.",
    "sv": "✅ Runtime har redan en Cursor-nyckel. Lämna tomt för att använda den.",
    "zh-Hans": "✅ Runtime 已有 Cursor 密钥。留空即可使用它。",
    "zh-Hant": "✅ Runtime 已有 Cursor 金鑰。留空即可使用它。",
}


def cursor_key_note(runtime_has_key: bool, language: str = "") -> str:
    return pick(CURSOR_KEY_NOTE, language) if runtime_has_key else ""
