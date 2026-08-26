import hashlib
import hmac
import html
import json
import os
from datetime import datetime

from aiohttp import web


LOGIN_PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>XPC Control</title><style>
body{margin:0;background:#080b12;color:#eef2ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(390px,88vw);background:#121827;border:1px solid #29324a;border-radius:20px;padding:30px}h1{margin:0 0 8px;color:#7c8cff}p{color:#9ca7bd}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:10px;border:1px solid #34405d;background:#0b1020;color:white;margin-top:12px}button{background:#5865f2;border:0;font-weight:700;cursor:pointer}.error{color:#ff7188}</style></head><body><form class=card method=post action=/login><h1>XPC Control</h1><p>Sign in with your private dashboard password.</p>__ERROR__<input type=password name=password placeholder='Dashboard password' required autofocus><button>Open dashboard</button></form></body></html>"""

DASHBOARD_PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><meta name=theme-color content='#090d18'><link rel=manifest href=/manifest.json><title>XPC Control</title><style>
*{box-sizing:border-box}body{margin:0;background:#080b12;color:#ecf1ff;font:14px system-ui}header{position:sticky;top:0;z-index:2;background:#0d1220eF;border-bottom:1px solid #252d42;padding:16px 5vw;display:flex;align-items:center;gap:15px}h1{margin:0;font-size:22px;color:#91a0ff}select,input,button{background:#121a2c;color:#eef2ff;border:1px solid #303b57;border-radius:9px;padding:9px}button{cursor:pointer}.logout{margin-left:auto}main{width:min(1200px,92vw);margin:25px auto}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.stat,.panel{background:#111827;border:1px solid #263049;border-radius:16px;padding:18px}.stat b{display:block;font-size:25px;color:#8d9cff;margin-top:5px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:15px}.panel h2{margin:0 0 14px}.command,.team{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid #232d43}.command:first-of-type,.team:first-of-type{border:0}.command small{display:block;color:#929db4}.switch{margin-left:auto;width:48px;height:26px;border-radius:20px;background:#354058;padding:3px}.switch.on{background:#45bd77}.switch i{display:block;width:20px;height:20px;background:white;border-radius:50%;transition:.15s}.switch.on i{margin-left:22px}.logs{max-height:500px;overflow:auto}.log{padding:9px 0;border-top:1px solid #232d43}.log small{color:#8d98ae}.danger{color:#ff758c}.good{color:#59d98e}@media(max-width:600px){header{flex-wrap:wrap}.logout{margin-left:0}}</style></head><body>
<header><h1>XPC Control</h1><select id=guild></select><button id=refresh>Refresh</button><form class=logout method=post action=/logout><button>Sign out</button></form></header>
<main><div class=stats><div class=stat>Status<b id=status>Online</b></div><div class=stat>Commands<b id=commandCount>—</b></div><div class=stat>Teams<b id=teamCount>—</b></div><div class=stat>Audit entries<b id=auditCount>—</b></div></div>
<div class=grid><section class=panel><h2>Command status</h2><div id=commands></div></section><section class=panel><h2>Add a team</h2><input id=teamName placeholder='Team name' style='width:100%;margin-bottom:9px'><select id=teamRole style='width:100%;margin-bottom:9px'></select><select id=teamOwner style='width:100%;margin-bottom:9px'></select><input id=rosterCap type=number min=1 max=99 value=22 placeholder='Roster limit' style='width:49%'><input id=startBudget type=number min=0 value=50 placeholder='Budget (M)' style='width:49%'><button id=addTeam style='width:100%;margin-top:10px;background:#5865f2'>ADD TEAM</button><p id=teamMessage></p><h2 style='margin-top:25px'>Club budgets</h2><div id=teams></div><h2 style='margin-top:25px'>Transfer window</h2><button id=windowToggle></button></section><section class='panel logs'><h2>Recent activity</h2><div id=logs></div></section></div></main>
<script>const csrf=__CSRF__;let state=null;const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,opt={}){opt.headers={...(opt.headers||{}),'X-Dashboard-Token':csrf};let r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}
async function loadGuilds(){let d=await api('/api/guilds');guild.innerHTML=d.guilds.map(g=>`<option value='${g.id}'>${esc(g.name)}</option>`).join('');if(d.guilds.length)load()}
async function load(){let id=guild.value;if(!id)return;state=await api('/api/state?guild_id='+id);commandCount.textContent=state.commands.length;teamCount.textContent=state.teams.length;auditCount.textContent=state.logs.length;
commands.innerHTML=state.commands.map(c=>`<div class=command><div><b>/${esc(c.name)}</b><small>${esc(c.description)}</small></div><button class='switch ${c.enabled?'on':''}' data-command='${esc(c.name)}'><i></i></button></div>`).join('');
teams.innerHTML=state.teams.map(t=>`<div class=team><b>${esc(t.name)}</b><input type=number min=0 value='${t.budget}' data-team='${esc(t.name)}' style='margin-left:auto;width:90px'><span>M</span></div>`).join('')||'No teams configured.';
teamRole.innerHTML=`<option value=''>Choose team role</option>`+state.roles.map(r=>`<option value='${r.id}'>${esc(r.name)}</option>`).join('');teamOwner.innerHTML=`<option value=''>Choose team owner</option>`+state.members.map(m=>`<option value='${m.id}'>${esc(m.name)}</option>`).join('');
logs.innerHTML=state.logs.map(l=>`<div class=log><b>${esc(l.action)}</b> by ${l.user_id?'&lt;@'+l.user_id+'&gt;':'System'}<br><small>${esc(l.details)} · ${esc(l.created_at)}</small></div>`).join('')||'No activity yet.';
windowToggle.textContent=state.transfer_window_open?'Open — click to close':'Closed — click to open';windowToggle.className=state.transfer_window_open?'good':'danger'}
commands.onclick=async e=>{let b=e.target.closest('[data-command]');if(!b)return;await api('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,command:b.dataset.command,enabled:!b.classList.contains('on')})});load()};
teams.onchange=async e=>{if(!e.target.dataset.team)return;await api('/api/budget',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,team:e.target.dataset.team,amount:Number(e.target.value)})});load()};
addTeam.onclick=async()=>{teamMessage.textContent='';try{await api('/api/team',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,name:teamName.value,role_id:teamRole.value,owner_id:teamOwner.value,roster_cap:Number(rosterCap.value),budget:Number(startBudget.value)})});teamName.value='';teamMessage.textContent='Team added successfully.';teamMessage.className='good';await load()}catch(e){teamMessage.textContent=e.message;teamMessage.className='danger'}};
windowToggle.onclick=async()=>{await api('/api/window',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,open:!state.transfer_window_open})});load()};guild.onchange=load;refresh.onclick=load;loadGuilds();if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js');</script></body></html>"""


class Dashboard:
    def __init__(self, bot, database) -> None:
        self.bot = bot
        self.db = database
        self.password = os.getenv("DASHBOARD_PASSWORD", "").strip()
        secret = os.getenv("DASHBOARD_SECRET", "").strip() or self.password
        self.token = hmac.new(secret.encode(), b"xpc-dashboard", hashlib.sha256).hexdigest()
        self.runner = None

    def authenticated(self, request: web.Request) -> bool:
        return bool(self.password) and hmac.compare_digest(request.cookies.get("xpc_session", ""), self.token)

    def api_authenticated(self, request: web.Request) -> bool:
        return self.authenticated(request) and hmac.compare_digest(request.headers.get("X-Dashboard-Token", ""), self.token)

    async def home(self, request):
        if not self.authenticated(request):
            return web.Response(text=LOGIN_PAGE.replace("__ERROR__", ""), content_type="text/html")
        return web.Response(text=DASHBOARD_PAGE.replace("__CSRF__", json.dumps(self.token)), content_type="text/html")

    async def login(self, request):
        form = await request.post()
        if not self.password or not hmac.compare_digest(str(form.get("password", "")), self.password):
            return web.Response(text=LOGIN_PAGE.replace("__ERROR__", "<p class=error>Incorrect password.</p>"), content_type="text/html", status=401)
        response = web.HTTPFound("/")
        response.set_cookie("xpc_session", self.token, httponly=True, secure=bool(os.getenv("RAILWAY_PROJECT_ID")), samesite="Strict", max_age=86400 * 30)
        return response

    async def logout(self, request):
        response = web.HTTPFound("/")
        response.del_cookie("xpc_session")
        return response

    def require_api(self, request):
        if not self.api_authenticated(request):
            raise web.HTTPUnauthorized(text="Not signed in")

    async def guilds(self, request):
        self.require_api(request)
        return web.json_response({"guilds": [{"id": str(g.id), "name": g.name} for g in self.bot.guilds]})

    async def state(self, request):
        self.require_api(request)
        guild_id = int(request.query["guild_id"])
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise web.HTTPNotFound(text="Server not found")
        statuses = self.db.command_statuses(guild_id)
        commands = [{"name": c.qualified_name, "description": c.description, "enabled": statuses.get(c.qualified_name, True)} for c in self.bot.tree.walk_commands() if getattr(c, "parent", None) is None]
        teams = [{"name": t["name"], "role_id": str(t["role_id"]), "budget": self.db.team_budget(guild_id, t["name"])} for t in self.db.teams(guild_id)]
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]
        members = [{"id": str(member.id), "name": member.display_name} for member in guild.members if not member.bot]
        logs = [dict(row) for row in self.db.audit_entries(guild_id)]
        return web.json_response({"commands": commands, "teams": teams, "roles": roles, "members": members, "logs": logs, "transfer_window_open": self.db.transfer_window_open(guild_id)})

    async def toggle(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); name = str(data["command"])
        valid = {c.qualified_name for c in self.bot.tree.walk_commands()}
        if name not in valid: raise web.HTTPBadRequest(text="Unknown command")
        enabled = bool(data["enabled"]); self.db.set_command_enabled(guild_id, name, enabled); self.db.add_audit(guild_id, None, "Dashboard command toggle", f"/{name} {'enabled' if enabled else 'disabled'}")
        return web.json_response({"ok": True})

    async def budget(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); amount = max(0, int(data["amount"])); team = self.db.team(guild_id, str(data["team"]))
        if not team: raise web.HTTPBadRequest(text="Unknown team")
        self.db.set_team_budget(guild_id, team["name"], amount); self.db.add_audit(guild_id, None, "Dashboard budget edit", f"{team['name']} = {amount}M")
        cog = self.bot.get_cog("ClubManagement")
        guild = self.bot.get_guild(guild_id)
        if cog and guild:
            await cog.refresh_budget_message(guild)
        return web.json_response({"ok": True})

    async def add_team(self, request):
        self.require_api(request)
        data = await request.json(); guild_id = int(data["guild_id"]); guild = self.bot.get_guild(guild_id)
        if guild is None: raise web.HTTPNotFound(text="Server not found")
        name = str(data.get("name", "")).strip(); role = guild.get_role(int(data.get("role_id") or 0)); owner = guild.get_member(int(data.get("owner_id") or 0))
        roster_cap = int(data.get("roster_cap", 22)); budget = max(0, int(data.get("budget", 0)))
        if not name or len(name) > 80: raise web.HTTPBadRequest(text="Enter a team name of 1–80 characters.")
        if role is None or role.is_default() or role.managed: raise web.HTTPBadRequest(text="Choose a normal Discord team role.")
        if owner is None: raise web.HTTPBadRequest(text="Choose a valid team owner.")
        if roster_cap < 1 or roster_cap > 99: raise web.HTTPBadRequest(text="Roster limit must be from 1 to 99.")
        if self.db.team(guild_id, name): raise web.HTTPBadRequest(text="A team with that name already exists.")
        try:
            self.db.add_team(guild_id, name, role.id, owner.id, None, roster_cap)
        except Exception:
            raise web.HTTPBadRequest(text="That Discord role is already assigned to another team.")
        self.db.set_team_budget(guild_id, name, budget)
        self.db.add_audit(guild_id, None, "Dashboard team added", f"{name}, owner {owner.id}, role {role.id}, {budget}M")
        cog = self.bot.get_cog("ClubManagement")
        if cog: await cog.refresh_budget_message(guild)
        return web.json_response({"ok": True})

    async def window(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); opened = bool(data["open"]); self.db.set_transfer_window(guild_id, opened); self.db.add_audit(guild_id, None, "Dashboard transfer window", "Opened" if opened else "Closed")
        return web.json_response({"ok": True})

    async def manifest(self, request):
        return web.json_response({"name": "XPC Bot Control", "short_name": "XPC Control", "start_url": "/", "display": "standalone", "background_color": "#080b12", "theme_color": "#090d18"})

    async def service_worker(self, request):
        return web.Response(text="self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('fetch',()=>{});", content_type="application/javascript")

    async def start(self) -> None:
        if not self.password:
            return
        app = web.Application(client_max_size=1024 * 1024)
        app.add_routes([web.get("/", self.home), web.post("/login", self.login), web.post("/logout", self.logout), web.get("/api/guilds", self.guilds), web.get("/api/state", self.state), web.post("/api/toggle", self.toggle), web.post("/api/budget", self.budget), web.post("/api/team", self.add_team), web.post("/api/window", self.window), web.get("/manifest.json", self.manifest), web.get("/sw.js", self.service_worker)])
        self.runner = web.AppRunner(app); await self.runner.setup(); site = web.TCPSite(self.runner, "0.0.0.0", int(os.getenv("PORT", "8080"))); await site.start()

