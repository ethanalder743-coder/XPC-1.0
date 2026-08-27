import hashlib
import hmac
import html
import json
import os
from datetime import datetime

from aiohttp import web


def league_table(team_names, results):
    table = {name: {"team": name, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "gd": 0, "points": 0} for name in team_names}
    for result in results:
        home, away = result["home_team"], result["away_team"]
        if home not in table or away not in table:
            continue
        hs, ars = int(result["home_score"]), int(result["away_score"])
        for name, scored, conceded in ((home, hs, ars), (away, ars, hs)):
            table[name]["played"] += 1; table[name]["gf"] += scored; table[name]["ga"] += conceded
        if hs == ars:
            table[home]["drawn"] += 1; table[away]["drawn"] += 1; table[home]["points"] += 1; table[away]["points"] += 1
        else:
            winner, loser = (home, away) if hs > ars else (away, home)
            table[winner]["won"] += 1; table[winner]["points"] += 3; table[loser]["lost"] += 1
    for row in table.values(): row["gd"] = row["gf"] - row["ga"]
    return sorted(table.values(), key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"].lower()))


LOGIN_PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>XPC Control</title><style>
body{margin:0;background:#080b12;color:#eef2ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(390px,88vw);background:#121827;border:1px solid #29324a;border-radius:20px;padding:30px}h1{margin:0 0 8px;color:#7c8cff}p{color:#9ca7bd}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:10px;border:1px solid #34405d;background:#0b1020;color:white;margin-top:12px}button{background:#5865f2;border:0;font-weight:700;cursor:pointer}.error{color:#ff7188}</style></head><body><form class=card method=post action=/login><h1>XPC Control</h1><p>Sign in with your private dashboard password.</p>__ERROR__<input type=password name=password placeholder='Dashboard password' required autofocus><button>Open dashboard</button></form></body></html>"""

LEGAL_STYLE = """<style>*{box-sizing:border-box}body{margin:0;background:#080b12;color:#edf1ff;font:16px/1.65 system-ui}main{width:min(850px,90vw);margin:55px auto;background:#111827;border:1px solid #29324a;border-radius:22px;padding:clamp(24px,5vw,52px)}h1{color:#91a0ff;margin:0}h2{margin-top:30px;color:#c7ceff}p,li{color:#b9c2d6}.date{color:#7f8ba5}</style>"""

TERMS_PAGE = f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>XPC Terms of Service</title>{LEGAL_STYLE}</head><body><main>
<h1>XPC Bot Terms of Service</h1><p class=date>Effective 27 August 2026</p>
<p>By inviting or using XPC, you agree to these terms and Discord's applicable rules. If you do not agree, do not use the bot.</p>
<h2>Use of XPC</h2><p>XPC provides Discord tools for Pro Clubs management, applications, moderation, tickets, statistics and server administration. You must not use it to break laws, abuse Discord, harass others, bypass permissions or interfere with the service.</p>
<h2>Server administration</h2><p>Server owners and authorised staff control their configuration and decisions. They are responsible for permissions, moderation actions, application questions and submitted content.</p>
<h2>Availability and termination</h2><p>The service is provided as available and may change, experience downtime or be discontinued. Access may be suspended for misuse, security risks or violation of these terms. To the extent allowed by law, XPC is not liable for indirect loss caused by use or unavailability of the service.</p>
<h2>Ownership and independence</h2><p>XPC's original code and branding remain the property of their respective owner. XPC is independently developed and is not affiliated with Discord, Electronic Arts, EA SPORTS or Byronic.</p>
<h2>Changes and contact</h2><p>These terms may be updated when the service changes. Continued use after an update means you accept the revised terms. For questions or removal requests, contact the XPC operator through the official XPC Discord community or your server administrator.</p>
</main></body></html>"""

PRIVACY_PAGE = f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>XPC Privacy Policy</title>{LEGAL_STYLE}</head><body><main>
<h1>XPC Bot Privacy Policy</h1><p class=date>Effective 27 August 2026</p>
<p>This policy explains what information XPC processes when you use the Discord bot.</p>
<h2>Information processed</h2><p>XPC may store Discord user, server, channel and role IDs; team and roster configuration; offers, transfers, budgets and results; saved-role records; ticket and application answers; moderation warnings and logs; invite attribution; and statistics or images users intentionally submit.</p>
<h2>How information is used</h2><p>Information is used only to operate requested bot features, preserve server configuration, restore permitted roles, provide audit records, prevent abuse and troubleshoot the service.</p>
<h2>Storage and retention</h2><p>Operational data is stored in the bot's database on its hosting provider. It is retained while needed to provide the service or until removed by an authorised administrator. Application answers and direct messages are processed only when a user chooses to submit them.</p>
<h2>Sharing</h2><p>XPC does not sell personal information. Data may be processed by Discord and the hosting provider Railway as needed to run the service, or disclosed when legally required or necessary to protect users and the service.</p>
<h2>Security and choices</h2><p>Reasonable safeguards are used, but no online system can guarantee absolute security. Users can stop using the bot. Server owners or affected users may request access, correction or deletion through the official XPC Discord community or their server administrator, subject to legal and security requirements.</p>
<h2>Children and changes</h2><p>Users must meet Discord's minimum age and any higher age required in their country. This policy may be updated when features or legal requirements change.</p>
<h2>Contact</h2><p>For privacy questions, contact the XPC operator through the official XPC Discord community.</p>
</main></body></html>"""

DASHBOARD_PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><meta name=theme-color content='#090d18'><link rel=manifest href=/manifest.json><title>XPC Control</title><style>
*{box-sizing:border-box}body{margin:0;background:#080b12;color:#ecf1ff;font:14px system-ui}header{position:sticky;top:0;z-index:2;background:#0d1220eF;border-bottom:1px solid #252d42;padding:16px 5vw;display:flex;align-items:center;gap:15px}h1{margin:0;font-size:22px;color:#91a0ff}select,input,button{background:#121a2c;color:#eef2ff;border:1px solid #303b57;border-radius:9px;padding:9px}button{cursor:pointer}.logout{margin-left:auto}main{width:min(1200px,92vw);margin:25px auto}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.stat,.panel{background:#111827;border:1px solid #263049;border-radius:16px;padding:18px}.stat b{display:block;font-size:25px;color:#8d9cff;margin-top:5px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:15px}.panel h2{margin:0 0 14px}.command,.team{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid #232d43}.command:first-of-type,.team:first-of-type{border:0}.command small{display:block;color:#929db4}.switch{margin-left:auto;width:48px;height:26px;border-radius:20px;background:#354058;padding:3px}.switch.on{background:#45bd77}.switch i{display:block;width:20px;height:20px;background:white;border-radius:50%;transition:.15s}.switch.on i{margin-left:22px}.logs{max-height:500px;overflow:auto}.log{padding:9px 0;border-top:1px solid #232d43}.log small{color:#8d98ae}.danger{color:#ff758c}.good{color:#59d98e}@media(max-width:600px){header{flex-wrap:wrap}.logout{margin-left:0}}</style></head><body>
<header><h1>XPC Control</h1><select id=guild></select><button id=refresh>Refresh</button><form class=logout method=post action=/logout><button>Sign out</button></form></header>
<main><div class=stats><div class=stat>Status<b id=status>Online</b></div><div class=stat>Commands<b id=commandCount>—</b></div><div class=stat>Teams<b id=teamCount>—</b></div><div class=stat>Audit entries<b id=auditCount>—</b></div></div>
<div class=grid><section class=panel><h2>Command status</h2><div id=commands></div></section><section class=panel><h2>Add a team</h2><input id=teamName placeholder='Team name' style='width:100%;margin-bottom:9px'><select id=teamRole style='width:100%;margin-bottom:9px'></select><select id=teamOwner style='width:100%;margin-bottom:9px'></select><input id=rosterCap type=number min=1 max=99 value=22 placeholder='Roster limit' style='width:49%'><input id=startBudget type=number min=0 value=50 placeholder='Budget (M)' style='width:49%'><button id=addTeam style='width:100%;margin-top:10px;background:#5865f2'>ADD TEAM</button><p id=teamMessage></p><h2 style='margin-top:25px'>Club budgets & logos</h2><div id=teams></div><h2 style='margin-top:25px'>Transfer window</h2><button id=windowToggle></button></section><section class='panel logs'><h2>Recent activity</h2><div id=logs></div></section>
<section class=panel><h2>Fixture editor</h2><select id=fixtureHome style='width:100%;margin-bottom:9px'></select><select id=fixtureAway style='width:100%;margin-bottom:9px'></select><input id=fixtureTime type=datetime-local style='width:100%;margin-bottom:9px'><input id=fixtureCompetition value='League' placeholder='Competition' style='width:100%;margin-bottom:9px'><button id=addFixture style='width:100%;background:#5865f2'>ADD FIXTURE</button><div id=fixtureList></div></section>
<section class=panel><h2>Trophy cabinet editor</h2><input id=trophyName placeholder='Trophy name' style='width:100%;margin-bottom:9px'><input id=trophyLogo placeholder='Trophy logo image URL' style='width:100%;margin-bottom:9px'><button id=addTrophy style='width:100%;background:#5865f2'>ADD TROPHY</button><h2 style='margin-top:24px'>Award a trophy</h2><select id=awardTrophy style='width:100%;margin-bottom:9px'></select><select id=awardTeam style='width:100%;margin-bottom:9px'></select><input id=awardSeason placeholder='Season, e.g. Season 1' style='width:100%;margin-bottom:9px'><button id=awardButton style='width:100%;background:#5865f2'>AWARD TROPHY</button><div id=winnerList></div></section></div></main>
<script>const csrf=__CSRF__;let state=null;const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,opt={}){opt.headers={...(opt.headers||{}),'X-Dashboard-Token':csrf};let r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}
async function loadGuilds(){let d=await api('/api/guilds');guild.innerHTML=d.guilds.map(g=>`<option value='${g.id}'>${esc(g.name)}</option>`).join('');if(d.guilds.length)load()}
async function load(){let id=guild.value;if(!id)return;state=await api('/api/state?guild_id='+id);commandCount.textContent=state.commands.length;teamCount.textContent=state.teams.length;auditCount.textContent=state.logs.length;
commands.innerHTML=state.commands.map(c=>`<div class=command><div><b>/${esc(c.name)}</b><small>${esc(c.description)}</small></div><button class='switch ${c.enabled?'on':''}' data-command='${esc(c.name)}'><i></i></button></div>`).join('');
teams.innerHTML=state.teams.map(t=>`<div class=team style='flex-wrap:wrap'><b>${esc(t.name)}</b><input type=number min=0 value='${t.budget}' data-team='${esc(t.name)}' style='margin-left:auto;width:82px'><span>M</span><input placeholder='Logo image URL' data-logo='${esc(t.name)}' style='width:100%'></div>`).join('')||'No teams configured.';
teamRole.innerHTML=`<option value=''>Choose team role</option>`+state.roles.map(r=>`<option value='${r.id}'>${esc(r.name)}</option>`).join('');teamOwner.innerHTML=`<option value=''>Choose team owner</option>`+state.members.map(m=>`<option value='${m.id}'>${esc(m.name)}</option>`).join('');
let teamOpts=state.teams.map(t=>`<option value='${esc(t.name)}'>${esc(t.name)}</option>`).join('');fixtureHome.innerHTML=`<option value=''>Home team</option>`+teamOpts;fixtureAway.innerHTML=`<option value=''>Away team</option>`+teamOpts;awardTeam.innerHTML=`<option value=''>Winning team</option>`+teamOpts;awardTrophy.innerHTML=`<option value=''>Choose trophy</option>`+state.trophies.map(t=>`<option value='${t.id}'>${esc(t.name)}</option>`).join('');fixtureList.innerHTML=state.fixtures.map(f=>`<div class=log><b>${esc(f.home_team)} vs ${esc(f.away_team)}</b><br><small>${esc(f.competition)} · ${esc(f.kickoff)}</small></div>`).join('')||'<p>No fixtures yet.</p>';winnerList.innerHTML=state.trophy_winners.map(w=>`<div class=log><b>${esc(w.team_name)}</b> won ${esc(w.trophy_name)}<br><small>${esc(w.season)}</small></div>`).join('')||'<p>No trophy winners yet.</p>';
logs.innerHTML=state.logs.map(l=>`<div class=log><b>${esc(l.action)}</b> by ${l.user_id?'&lt;@'+l.user_id+'&gt;':'System'}<br><small>${esc(l.details)} · ${esc(l.created_at)}</small></div>`).join('')||'No activity yet.';
windowToggle.textContent=state.transfer_window_open?'Open — click to close':'Closed — click to open';windowToggle.className=state.transfer_window_open?'good':'danger'}
commands.onclick=async e=>{let b=e.target.closest('[data-command]');if(!b)return;await api('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,command:b.dataset.command,enabled:!b.classList.contains('on')})});load()};
teams.onchange=async e=>{if(!e.target.dataset.team)return;await api('/api/budget',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,team:e.target.dataset.team,amount:Number(e.target.value)})});load()};
teams.onkeydown=async e=>{if(e.key!=='Enter'||!e.target.dataset.logo)return;await api('/api/team-logo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,team:e.target.dataset.logo,logo_url:e.target.value})});load()};
addTeam.onclick=async()=>{teamMessage.textContent='';try{await api('/api/team',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,name:teamName.value,role_id:teamRole.value,owner_id:teamOwner.value,roster_cap:Number(rosterCap.value),budget:Number(startBudget.value)})});teamName.value='';teamMessage.textContent='Team added successfully.';teamMessage.className='good';await load()}catch(e){teamMessage.textContent=e.message;teamMessage.className='danger'}};
windowToggle.onclick=async()=>{await api('/api/window',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,open:!state.transfer_window_open})});load()};
addFixture.onclick=async()=>{await api('/api/fixture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,home:fixtureHome.value,away:fixtureAway.value,kickoff:fixtureTime.value,competition:fixtureCompetition.value})});load()};
addTrophy.onclick=async()=>{await api('/api/trophy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,name:trophyName.value,logo_url:trophyLogo.value})});trophyName.value='';trophyLogo.value='';load()};
awardButton.onclick=async()=>{await api('/api/trophy-award',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value,trophy_id:awardTrophy.value,team:awardTeam.value,season:awardSeason.value})});load()};guild.onchange=load;refresh.onclick=load;loadGuilds();if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js');</script></body></html>"""


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
        bearer = request.headers.get("Authorization", "")
        bearer_ok = bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], self.token)
        browser_ok = self.authenticated(request) and hmac.compare_digest(request.headers.get("X-Dashboard-Token", ""), self.token)
        return bearer_ok or browser_ok

    async def home(self, request):
        if not self.password:
            return web.Response(
                text="XPC bot is online. Set DASHBOARD_PASSWORD in Railway to enable the private control panel.",
                content_type="text/plain",
                status=503,
            )
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

    async def login_page(self, request):
        raise web.HTTPFound("/")

    async def terms(self, request):
        return web.Response(text=TERMS_PAGE, content_type="text/html")

    async def privacy(self, request):
        return web.Response(text=PRIVACY_PAGE, content_type="text/html")

    async def desktop_login(self, request):
        data = await request.json()
        if not self.password or not hmac.compare_digest(str(data.get("password", "")), self.password):
            raise web.HTTPUnauthorized(text="Incorrect dashboard password")
        return web.json_response({"token": self.token})

    async def logout(self, request):
        response = web.HTTPFound("/")
        response.del_cookie("xpc_session")
        return response

    def require_api(self, request):
        if not self.api_authenticated(request):
            raise web.HTTPUnauthorized(text="Not signed in")

    async def guilds(self, request):
        self.require_api(request)
        return web.json_response({"guilds": [
            {
                "id": str(g.id),
                "name": g.name,
                "icon_url": str(g.icon.url) if g.icon else None,
                "member_count": g.member_count or len(g.members),
                "owner_id": str(g.owner_id),
            }
            for g in sorted(self.bot.guilds, key=lambda item: item.name.casefold())
        ]})

    async def state(self, request):
        self.require_api(request)
        guild_id = int(request.query["guild_id"])
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise web.HTTPNotFound(text="Server not found")
        statuses = self.db.command_statuses(guild_id)
        commands = [
            {
                "name": command.qualified_name,
                "description": command.description,
                "enabled": statuses.get(command.qualified_name, True),
                "category": command.qualified_name.split()[0].title(),
            }
            for command in sorted(
                (item for item in self.bot.tree.walk_commands() if not hasattr(item, "commands")),
                key=lambda item: item.qualified_name,
            )
        ]
        teams = [{"name": t["name"], "role_id": str(t["role_id"]), "budget": self.db.team_budget(guild_id, t["name"])} for t in self.db.teams(guild_id)]
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]
        members = [{"id": str(member.id), "name": member.display_name} for member in guild.members if not member.bot]
        logs = [dict(row) for row in self.db.audit_entries(guild_id)]
        fixtures = [dict(row) for row in self.db.fixtures(guild_id)]
        trophies = [dict(row) for row in self.db.trophies(guild_id)]
        winners = [dict(row) for row in self.db.trophy_winners(guild_id)]
        results = [dict(row) for row in self.db.results(guild_id)]
        standings = league_table([team["name"] for team in teams], results)
        return web.json_response({"commands": commands, "teams": teams, "roles": roles, "members": members, "logs": logs, "fixtures": fixtures, "trophies": trophies, "trophy_winners": winners, "results": results, "standings": standings, "transfer_window_open": self.db.transfer_window_open(guild_id)})

    async def public_league(self, request):
        guild_id = int(request.query.get("guild_id", "0"))
        guild = self.bot.get_guild(guild_id)
        if guild is None: raise web.HTTPNotFound(text="League server not found")
        raw_teams = self.db.teams(guild_id)
        teams = []
        for team in raw_teams:
            role = guild.get_role(int(team["role_id"]))
            owner = guild.get_member(int(team["owner_id"] or 0))
            teams.append({"name": team["name"], "role_id": str(team["role_id"]), "role_name": role.name if role else team["name"], "colour": f"#{role.colour.value:06x}" if role and role.colour.value else "#7387ff", "owner": owner.name if owner else None, "owner_id": str(team["owner_id"]) if team["owner_id"] else None, "logo_url": team["logo_url"], "budget": self.db.team_budget(guild_id, team["name"]), "roster_cap": team["roster_cap"], "roster_size": len(self.db.team_member_ids(guild_id, team["name"]))})
        week = self.db.totw_week(guild_id); submissions = self.db.totw_submissions(guild_id, week); totw = []
        for group, label, count in (("GK","GK",1),("CB/FB","DEF",3),("CDM","CDM",2),("CAM","CAM",1),("WM","WM",2),("ST","ST",2)):
            for row in [r for r in submissions if r["position_group"] == group][:count]:
                member = guild.get_member(int(row["user_id"]))
                totw.append({"position": label, "user_id": str(row["user_id"]), "username": member.name if member else f"Player {row['user_id']}", "team": row["team_name"], "score": row["score"]})
        results = [dict(row) for row in self.db.results(guild_id)]
        payload = {"league": {"id": str(guild.id), "name": guild.name, "icon_url": str(guild.icon.url) if guild.icon else None}, "teams": teams, "standings": league_table([t["name"] for t in teams], results), "fixtures": [dict(row) for row in self.db.fixtures(guild_id)], "results": results, "totw": {"week": week, "players": totw}, "trophies": [dict(row) for row in self.db.trophies(guild_id)], "trophy_winners": [dict(row) for row in self.db.trophy_winners(guild_id)]}
        response = web.json_response(payload); response.headers["Access-Control-Allow-Origin"] = "*"; response.headers["Cache-Control"] = "public, max-age=30"; return response

    async def add_fixture(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); home = str(data.get("home", "")); away = str(data.get("away", "")); kickoff = str(data.get("kickoff", "")); competition = str(data.get("competition", "League")).strip() or "League"
        if not self.db.team(guild_id, home) or not self.db.team(guild_id, away) or home.lower() == away.lower(): raise web.HTTPBadRequest(text="Choose two different configured teams.")
        if not kickoff: raise web.HTTPBadRequest(text="Choose a fixture date and time.")
        self.db.add_fixture(guild_id, home, away, kickoff, competition); self.db.add_audit(guild_id, None, "Dashboard fixture added", f"{home} vs {away} - {kickoff}"); return web.json_response({"ok": True})

    async def team_logo(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); name = str(data.get("team", "")); url = str(data.get("logo_url", "")).strip()
        team = self.db.team(guild_id, name)
        if not team: raise web.HTTPBadRequest(text="Unknown team")
        if url and not url.startswith(("https://", "http://")): raise web.HTTPBadRequest(text="Logo must be a full image URL.")
        self.db.update_team_logo(guild_id, name, url, team["emoji_id"]); self.db.add_audit(guild_id, None, "Dashboard team logo", name); return web.json_response({"ok": True})

    async def add_trophy(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); name = str(data.get("name", "")).strip(); url = str(data.get("logo_url", "")).strip()
        if not name: raise web.HTTPBadRequest(text="Enter a trophy name.")
        try: self.db.add_trophy(guild_id, name, url or None)
        except Exception: raise web.HTTPBadRequest(text="That trophy already exists.")
        self.db.add_audit(guild_id, None, "Dashboard trophy added", name); return web.json_response({"ok": True})

    async def award_trophy(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); trophy_id = int(data["trophy_id"]); team = str(data["team"]); season = str(data.get("season", "")).strip()
        if not self.db.team(guild_id, team) or not season: raise web.HTTPBadRequest(text="Choose a team and enter a season.")
        if trophy_id not in {int(t["id"]) for t in self.db.trophies(guild_id)}: raise web.HTTPBadRequest(text="Unknown trophy.")
        self.db.award_trophy(guild_id, trophy_id, team, season); self.db.add_audit(guild_id, None, "Dashboard trophy awarded", f"{team} - {season}"); return web.json_response({"ok": True})

    async def toggle(self, request):
        self.require_api(request); data = await request.json(); guild_id = int(data["guild_id"]); name = str(data["command"])
        valid = {c.qualified_name for c in self.bot.tree.walk_commands()}
        if name not in valid: raise web.HTTPBadRequest(text="Unknown command")
        enabled = bool(data["enabled"]); self.db.set_command_enabled(guild_id, name, enabled); self.db.add_audit(guild_id, None, "Dashboard command toggle", f"/{name} {'enabled' if enabled else 'disabled'}")
        return web.json_response({"ok": True})

    async def toggle_all(self, request):
        self.require_api(request)
        data = await request.json()
        guild_id = int(data["guild_id"])
        if self.bot.get_guild(guild_id) is None:
            raise web.HTTPNotFound(text="Server not found")
        enabled = bool(data["enabled"])
        names = [
            command.qualified_name
            for command in self.bot.tree.walk_commands()
            if not hasattr(command, "commands")
        ]
        for name in names:
            self.db.set_command_enabled(guild_id, name, enabled)
        self.db.add_audit(
            guild_id,
            None,
            "Dashboard all commands",
            f"{len(names)} commands {'enabled' if enabled else 'disabled'}",
        )
        return web.json_response({"ok": True, "count": len(names)})

    async def update_result(self, request):
        self.require_api(request)
        data = await request.json()
        guild_id = int(data["guild_id"])
        result_id = int(data["result_id"])
        home_score = int(data["home_score"])
        away_score = int(data["away_score"])
        if not 0 <= home_score <= 99 or not 0 <= away_score <= 99:
            raise web.HTTPBadRequest(text="Scores must be between 0 and 99.")
        result = self.db.result(guild_id, result_id)
        if result is None:
            raise web.HTTPNotFound(text="Result not found")
        self.db.update_result(guild_id, result_id, home_score, away_score)
        self.db.add_audit(
            guild_id, None, "Dashboard result updated",
            f"#{result_id} {result['home_team']} {home_score}-{away_score} {result['away_team']}",
        )
        return web.json_response({"ok": True})

    async def delete_result(self, request):
        self.require_api(request)
        data = await request.json()
        guild_id = int(data["guild_id"])
        result_id = int(data["result_id"])
        result = self.db.result(guild_id, result_id)
        if result is None:
            raise web.HTTPNotFound(text="Result not found")
        self.db.delete_result(guild_id, result_id)
        self.db.add_audit(
            guild_id, None, "Dashboard result deleted",
            f"#{result_id} {result['home_team']} {result['home_score']}-{result['away_score']} {result['away_team']}",
        )
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
        app = web.Application(client_max_size=1024 * 1024)
        app.add_routes([web.get("/", self.home), web.get("/login", self.login_page), web.post("/login", self.login), web.post("/logout", self.logout), web.get("/terms", self.terms), web.get("/terms-of-service", self.terms), web.get("/privacy", self.privacy), web.get("/privacy-policy", self.privacy), web.post("/api/desktop/login", self.desktop_login), web.get("/api/guilds", self.guilds), web.get("/api/state", self.state), web.get("/api/public/league", self.public_league), web.post("/api/toggle", self.toggle), web.post("/api/toggle-all", self.toggle_all), web.post("/api/result-update", self.update_result), web.post("/api/result-delete", self.delete_result), web.post("/api/budget", self.budget), web.post("/api/team", self.add_team), web.post("/api/team-logo", self.team_logo), web.post("/api/fixture", self.add_fixture), web.post("/api/trophy", self.add_trophy), web.post("/api/trophy-award", self.award_trophy), web.post("/api/window", self.window), web.get("/manifest.json", self.manifest), web.get("/sw.js", self.service_worker)])
        self.runner = web.AppRunner(app); await self.runner.setup(); site = web.TCPSite(self.runner, "0.0.0.0", int(os.getenv("PORT", "8080"))); await site.start()

