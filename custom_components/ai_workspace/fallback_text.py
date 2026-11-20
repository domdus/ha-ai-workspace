"""The short chat notices of the agent fallback, in every language AI Workspace ships.

{agent} is the agent that stopped, {next} the one that goes on, {reset} a time like 18:30.
"""

from __future__ import annotations

from .local_text import pick

# Why an agent stopped, as a short phrase after its name.
REASONS: dict[str, dict[str, str]] = {
    "en": {
        "limit_reset": "at its limit (reset {reset})",
        "limit": "at its limit",
        "auth": "sign-in expired",
        "timeout": "did not answer in time",
        "connection": "not reachable",
        "overloaded": "overloaded",
    },
    "de": {
        "limit_reset": "am Limit (Reset {reset})",
        "limit": "am Limit",
        "auth": "Anmeldung abgelaufen",
        "timeout": "antwortet nicht rechtzeitig",
        "connection": "nicht erreichbar",
        "overloaded": "überlastet",
    },
    "fr": {
        "limit_reset": "a atteint sa limite (réinitialisation {reset})",
        "limit": "a atteint sa limite",
        "auth": "connexion expirée",
        "timeout": "n'a pas répondu à temps",
        "connection": "injoignable",
        "overloaded": "surchargé",
    },
    "es": {
        "limit_reset": "llegó a su límite (se restablece a las {reset})",
        "limit": "llegó a su límite",
        "auth": "inicio de sesión caducado",
        "timeout": "no respondió a tiempo",
        "connection": "no disponible",
        "overloaded": "sobrecargado",
    },
    "it": {
        "limit_reset": "ha raggiunto il limite (reset alle {reset})",
        "limit": "ha raggiunto il limite",
        "auth": "accesso scaduto",
        "timeout": "non ha risposto in tempo",
        "connection": "non raggiungibile",
        "overloaded": "sovraccarico",
    },
    "nl": {
        "limit_reset": "zit aan zijn limiet (reset {reset})",
        "limit": "zit aan zijn limiet",
        "auth": "aanmelding verlopen",
        "timeout": "antwoordde niet op tijd",
        "connection": "niet bereikbaar",
        "overloaded": "overbelast",
    },
    "pl": {
        "limit_reset": "osiągnął limit (reset {reset})",
        "limit": "osiągnął limit",
        "auth": "logowanie wygasło",
        "timeout": "nie odpowiedział na czas",
        "connection": "niedostępny",
        "overloaded": "przeciążony",
    },
    "cs": {
        "limit_reset": "dosáhl limitu (obnovení {reset})",
        "limit": "dosáhl limitu",
        "auth": "přihlášení vypršelo",
        "timeout": "neodpověděl včas",
        "connection": "nedostupný",
        "overloaded": "přetížený",
    },
    "sv": {
        "limit_reset": "har nått sin gräns (återställs {reset})",
        "limit": "har nått sin gräns",
        "auth": "inloggningen har gått ut",
        "timeout": "svarade inte i tid",
        "connection": "inte nåbar",
        "overloaded": "överbelastad",
    },
    "ru": {
        "limit_reset": "достиг лимита (сброс в {reset})",
        "limit": "достиг лимита",
        "auth": "вход истёк",
        "timeout": "не ответил вовремя",
        "connection": "недоступен",
        "overloaded": "перегружен",
    },
    "ko": {
        "limit_reset": "한도 도달 ({reset} 초기화)",
        "limit": "한도 도달",
        "auth": "로그인 만료",
        "timeout": "제시간에 응답하지 않음",
        "connection": "연결할 수 없음",
        "overloaded": "과부하",
    },
    "zh-Hans": {
        "limit_reset": "已达上限（{reset} 重置）",
        "limit": "已达上限",
        "auth": "登录已过期",
        "timeout": "未及时响应",
        "connection": "无法连接",
        "overloaded": "过载",
    },
    "zh-Hant": {
        "limit_reset": "已達上限（{reset} 重設）",
        "limit": "已達上限",
        "auth": "登入已過期",
        "timeout": "未及時回應",
        "connection": "無法連線",
        "overloaded": "過載",
    },
    "az": {
        "limit_reset": "limitə çatdı (sıfırlanma {reset})",
        "limit": "limitə çatdı",
        "auth": "giriş müddəti bitdi",
        "timeout": "vaxtında cavab vermədi",
        "connection": "əlçatan deyil",
        "overloaded": "həddindən artıq yüklənib",
    },
    "eo": {
        "limit_reset": "atingis sian limon (restarigo je {reset})",
        "limit": "atingis sian limon",
        "auth": "ensaluto eksvalidiĝis",
        "timeout": "ne respondis ĝustatempe",
        "connection": "ne atingebla",
        "overloaded": "troŝarĝita",
    },
}

# switch: {agent} {reason}. {next} goes on. paused: nobody left. resumed / promoted: going on again.
SENTENCES: dict[str, dict[str, str]] = {
    "en": {
        "switch": "{agent} {reason}. {next} continues.",
        "paused": "No agent can continue right now. The task is paused and goes on by itself{when}.",
        "when": " around {reset}",
        "none": "No agent in the fallback list can do this task (it needs a Runtime agent with a workspace).",
        "gave_up": "No agent came back within a day. The task stopped.",
        "resumed": "{next} is available again and continues.",
        "promoted": "Back to {next}.",
    },
    "de": {
        "switch": "{agent} {reason}. {next} macht weiter.",
        "paused": "Gerade kann kein Agent weitermachen. Die Aufgabe ist pausiert und geht von selbst weiter{when}.",
        "when": " (ca. {reset})",
        "none": "Kein Agent in der Fallback-Liste kann diese Aufgabe übernehmen (sie braucht einen Runtime-Agent mit Workspace).",
        "gave_up": "Innerhalb eines Tages kam kein Agent zurück. Die Aufgabe wurde beendet.",
        "resumed": "{next} ist wieder verfügbar und macht weiter.",
        "promoted": "Zurück zu {next}.",
    },
    "fr": {
        "switch": "{agent} : {reason}. {next} prend le relais.",
        "paused": "Aucun agent ne peut continuer pour l'instant. La tâche est en pause et reprendra d'elle-même{when}.",
        "when": " vers {reset}",
        "none": "Aucun agent de la liste de secours ne peut faire cette tâche (il faut un agent Runtime avec espace de travail).",
        "gave_up": "Aucun agent n'est revenu en une journée. La tâche est arrêtée.",
        "resumed": "{next} est de nouveau disponible et continue.",
        "promoted": "Retour à {next}.",
    },
    "es": {
        "switch": "{agent}: {reason}. {next} continúa.",
        "paused": "Ningún agente puede continuar ahora. La tarea está en pausa y seguirá sola{when}.",
        "when": " hacia las {reset}",
        "none": "Ningún agente de la lista de respaldo puede hacer esta tarea (necesita un agente Runtime con espacio de trabajo).",
        "gave_up": "Ningún agente volvió en un día. La tarea se detuvo.",
        "resumed": "{next} vuelve a estar disponible y continúa.",
        "promoted": "De vuelta a {next}.",
    },
    "it": {
        "switch": "{agent}: {reason}. {next} continua.",
        "paused": "Nessun agente può continuare ora. L'attività è in pausa e riprenderà da sola{when}.",
        "when": " verso le {reset}",
        "none": "Nessun agente dell'elenco di riserva può svolgere questa attività (serve un agente Runtime con workspace).",
        "gave_up": "Nessun agente è tornato entro un giorno. L'attività è stata interrotta.",
        "resumed": "{next} è di nuovo disponibile e continua.",
        "promoted": "Di nuovo con {next}.",
    },
    "nl": {
        "switch": "{agent} {reason}. {next} gaat verder.",
        "paused": "Geen agent kan nu verder. De taak is gepauzeerd en gaat vanzelf verder{when}.",
        "when": " rond {reset}",
        "none": "Geen agent in de fallbacklijst kan deze taak doen (er is een Runtime-agent met werkruimte nodig).",
        "gave_up": "Binnen een dag kwam geen agent terug. De taak is gestopt.",
        "resumed": "{next} is weer beschikbaar en gaat verder.",
        "promoted": "Terug naar {next}.",
    },
    "pl": {
        "switch": "{agent}: {reason}. {next} kontynuuje.",
        "paused": "Żaden agent nie może teraz kontynuować. Zadanie jest wstrzymane i wznowi się samo{when}.",
        "when": " około {reset}",
        "none": "Żaden agent z listy zapasowej nie może wykonać tego zadania (potrzebny agent Runtime z przestrzenią roboczą).",
        "gave_up": "Żaden agent nie wrócił w ciągu doby. Zadanie zostało zatrzymane.",
        "resumed": "{next} jest znów dostępny i kontynuuje.",
        "promoted": "Powrót do {next}.",
    },
    "cs": {
        "switch": "{agent}: {reason}. {next} pokračuje.",
        "paused": "Teď nemůže pokračovat žádný agent. Úloha je pozastavena a sama pokračuje{when}.",
        "when": " kolem {reset}",
        "none": "Žádný agent v záložním seznamu tuto úlohu nezvládne (je potřeba agent Runtime s pracovním prostorem).",
        "gave_up": "Během dne se žádný agent nevrátil. Úloha byla ukončena.",
        "resumed": "{next} je znovu dostupný a pokračuje.",
        "promoted": "Zpět na {next}.",
    },
    "sv": {
        "switch": "{agent} {reason}. {next} fortsätter.",
        "paused": "Ingen agent kan fortsätta just nu. Uppgiften är pausad och fortsätter av sig själv{when}.",
        "when": " runt {reset}",
        "none": "Ingen agent i reservlistan kan göra den här uppgiften (den behöver en Runtime-agent med arbetsyta).",
        "gave_up": "Ingen agent kom tillbaka inom ett dygn. Uppgiften avbröts.",
        "resumed": "{next} är tillgänglig igen och fortsätter.",
        "promoted": "Tillbaka till {next}.",
    },
    "ru": {
        "switch": "{agent}: {reason}. Продолжает {next}.",
        "paused": "Сейчас ни один агент не может продолжить. Задача приостановлена и продолжится сама{when}.",
        "when": " около {reset}",
        "none": "Ни один агент из резервного списка не может выполнить эту задачу (нужен агент Runtime с рабочей областью).",
        "gave_up": "За сутки ни один агент не вернулся. Задача остановлена.",
        "resumed": "{next} снова доступен и продолжает.",
        "promoted": "Снова {next}.",
    },
    "ko": {
        "switch": "{agent}: {reason}. {next}이(가) 이어서 합니다.",
        "paused": "지금은 이어서 할 에이전트가 없습니다. 작업이 일시 중지되었고 자동으로 계속됩니다{when}.",
        "when": " ({reset}경)",
        "none": "대체 목록의 어떤 에이전트도 이 작업을 할 수 없습니다(작업 공간이 있는 Runtime 에이전트가 필요합니다).",
        "gave_up": "하루 안에 돌아온 에이전트가 없습니다. 작업이 중지되었습니다.",
        "resumed": "{next}을(를) 다시 사용할 수 있어 이어서 합니다.",
        "promoted": "{next}(으)로 돌아왔습니다.",
    },
    "zh-Hans": {
        "switch": "{agent}{reason}。{next} 接着处理。",
        "paused": "目前没有可继续的代理。任务已暂停，将自动继续{when}。",
        "when": "（约 {reset}）",
        "none": "备用列表中没有代理能完成此任务（需要带工作区的 Runtime 代理）。",
        "gave_up": "一天内没有代理恢复。任务已停止。",
        "resumed": "{next} 已恢复，继续处理。",
        "promoted": "已切回 {next}。",
    },
    "zh-Hant": {
        "switch": "{agent}{reason}。{next} 接著處理。",
        "paused": "目前沒有可繼續的代理。任務已暫停，將自動繼續{when}。",
        "when": "（約 {reset}）",
        "none": "備用清單中沒有代理能完成此任務（需要具備工作區的 Runtime 代理）。",
        "gave_up": "一天內沒有代理恢復。任務已停止。",
        "resumed": "{next} 已恢復，繼續處理。",
        "promoted": "已切回 {next}。",
    },
    "az": {
        "switch": "{agent}: {reason}. {next} davam edir.",
        "paused": "Hazırda heç bir agent davam edə bilmir. Tapşırıq dayandırılıb və özü davam edəcək{when}.",
        "when": " (təxminən {reset})",
        "none": "Ehtiyat siyahısındakı heç bir agent bu tapşırığı edə bilməz (iş sahəsi olan Runtime agenti lazımdır).",
        "gave_up": "Bir gün ərzində heç bir agent qayıtmadı. Tapşırıq dayandırıldı.",
        "resumed": "{next} yenidən əlçatandır və davam edir.",
        "promoted": "Yenidən {next}.",
    },
    "eo": {
        "switch": "{agent} {reason}. {next} daŭrigas.",
        "paused": "Neniu agento povas daŭrigi nun. La tasko estas paŭzigita kaj daŭros memstare{when}.",
        "when": " ĉirkaŭ {reset}",
        "none": "Neniu agento en la rezerva listo povas fari ĉi tiun taskon (ĝi bezonas Runtime-agenton kun laborspaco).",
        "gave_up": "Neniu agento revenis ene de tago. La tasko ĉesis.",
        "resumed": "{next} denove disponeblas kaj daŭrigas.",
        "promoted": "Reen al {next}.",
    },
}


def switch_text(language: str, kind: str, agent: str, next_agent: str, reset: str = "") -> str:
    reasons = pick(REASONS, language)
    key = "limit_reset" if kind == "limit" and reset else kind
    reason = str(reasons.get(key) or reasons.get("limit") or "").format(reset=reset)
    return str(pick(SENTENCES, language)["switch"]).format(agent=agent, reason=reason, next=next_agent)


def notice_text(language: str, key: str, *, next_agent: str = "", reset: str = "") -> str:
    table = pick(SENTENCES, language)
    when = str(table["when"]).format(reset=reset) if reset else ""
    return str(table[key]).format(next=next_agent, when=when, reset=reset)
