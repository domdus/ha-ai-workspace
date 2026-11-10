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
