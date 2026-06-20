let globalData = {
    matches: [], teams: {}, players: {}, broadcasts: {}, powerRanking: [], playerRatings: {}
};

const posMap = { 'FW': '前锋 (FW)', 'MF': '中场 (MF)', 'DF': '后卫 (DF)', 'GK': '门将 (GK)' };
const statusMap = { 'upcoming': '未开赛', 'live': '直播中', 'finished': '已完赛' };
const statsI18n = {
    'goals': '进球数', 'caps': '国家队出场', 'clean_sheets': '零封场次',
    'wc_winner': '世界杯冠军成员', 'assists': '助攻数',
    'pass_accuracy': '传球成功率', 'tackles': '抢断次数', 'saves': '扑救次数'
};

function esc(s) {
    if (s == null) return '';
    var str = String(s);
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
}

// ── Timer management ──────────────────────────────────────────────────

let _dataTimer = null;
let _scrapeTimer = null;

function startTimers(intervalMin) {
    stopTimers();
    _dataTimer = setInterval(function() { loadData(); }, intervalMin * 60 * 1000);
    _scrapeTimer = setInterval(function() { triggerUpdate(); }, 6 * intervalMin * 60 * 1000);
}

function stopTimers() {
    if (_dataTimer) { clearInterval(_dataTimer); _dataTimer = null; }
    if (_scrapeTimer) { clearInterval(_scrapeTimer); _scrapeTimer = null; }
}

async function loadSettings() {
    try {
        var res = await fetch('/api/settings');
        var json = await res.json();
        if (json.status === 'success') {
            var interval = parseInt(json.settings.refresh_interval) || 5;
            interval = Math.max(1, Math.min(interval, 60));
            var inp = document.getElementById('refresh-interval-input');
            if (inp) inp.value = interval;
            startTimers(interval);
        }
    } catch(e) { startTimers(5); }
}

async function saveRefreshInterval(val) {
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_interval: parseInt(val) || 5 })
        });
    } catch(e) {}
}

function showError(msg) {
    var banner = document.getElementById('error-banner');
    var text = document.getElementById('error-banner-text');
    if (banner && text) {
        text.textContent = msg;
        banner.style.display = 'block';
        setTimeout(function() { banner.style.display = 'none'; }, 8000);
    }
}

async function loadData() {
    try {
        const res = await fetch('/api/data');
        const json = await res.json();
        if(json.status === 'success') {
            globalData = json.data;
            globalData.playerRatings = globalData.playerRatings || {};
            globalData.powerRanking = globalData.powerRanking || [];
            console.log('loadData: success, teams=' + Object.keys(json.data.teams).length + ' players=' + Object.keys(json.data.players).length + ' matches=' + json.data.matches.length);
            renderAll();
        } else {
            showError("数据加载失败: " + json.message);
            console.error('loadData: API returned error:', json);
        }
    } catch(e) {
        showError("网络连接异常，请检查服务器是否运行");
        console.error('loadData: fetch failed:', e);
        // Still try to render history (uses hardcoded data, no API needed)
        try { renderHistory(); } catch(e2) {}
    }
}

function switchView(viewId, el) {
    document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + viewId).classList.add('active');
    
    if (el) {
        document.querySelectorAll('.tree-link').forEach(l => l.classList.remove('active'));
        el.classList.add('active');
    }
}

async function triggerUpdate() {
    const btn = document.getElementById('refresh-btn');
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add('refreshing');
    btn.innerHTML = '<span class="spin-icon">🔄</span> 正在通讯同步...';
    try {
        const res = await fetch('/api/trigger_scrape', {method: 'POST'});
        const json = await res.json();
        if(json.status === 'success') {
            await loadData();
        } else {
            showError("数据采集失败: " + json.message);
        }
    } catch(e) {
        showError("采集网络异常，请稍后重试");
    } finally {
        btn.disabled = false;
        btn.classList.remove('refreshing');
        btn.innerHTML = '<span class="spin-icon">🔄</span> 实时更新战况';
    }
}

function renderAll() {
    // Wrap each render in try-catch so one failure doesn't block the rest
    var renderers = [
        ['赛事看板', function() { renderMatches('live'); }],
        ['全部比赛', function() { renderMatches('all'); }],
        ['球队巡礼', function() { renderTeams(); }],
        ['小组积分榜', function() { renderStandings(); }],
        ['射手榜', function() { renderScorers(); }],
        ['晋级树图', function() { renderBracket(); }],
        ['夺冠热门', function() { renderPowerRanking(); }],
        ['历届冠军', function() { renderHistory(); }]
    ];
    for (var i = 0; i < renderers.length; i++) {
        try {
            renderers[i][1]();
        } catch(e) {
            console.error('renderAll: ' + renderers[i][0] + ' failed:', e);
        }
    }
}

async function loadPowerRanking() {
    try {
        var res = await fetch('/api/power_ranking');
        var json = await res.json();
        if (json.status === 'success') {
            globalData.powerRanking = json.ranking;
            renderPowerRanking();
        }
    } catch(e) {}
}

async function loadPlayerRatings() {
    try {
        var res = await fetch('/api/player_ratings');
        var json = await res.json();
        if (json.status === 'success') {
            globalData.playerRatings = json.ratings;
            globalData.playerRanking = json.ranking;
            renderMatches('live');
            renderMatches('all');
            renderPlayerRatings();
        }
    } catch(e) {}
}

// ================= RENDER LOGIC =================

function renderMatches(type) {
    const containerId = type === 'live' ? 'matches-live-container' : 'matches-all-container';
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    
    let matches = globalData.matches;
    if (type === 'live') {
        matches = matches.filter(m => m.status === 'upcoming' || m.status === 'live');
    }
    
    if(matches.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding: 50px; color: var(--text-muted);">当前视图暂无赛事记录</div>';
        return;
    }
    
    // Countdown logic for 'live'  — 每秒刷新, 归零后自动重载数据
    if (type === 'live') {
        const upcoming = matches.filter(m => m.status === 'upcoming').sort((a,b) => new Date(a.match_time_utc) - new Date(b.match_time_utc));
        if(upcoming.length > 0) {
            const targetDate = new Date(upcoming[0].match_time_utc).getTime();
            window.countdownInterval && clearInterval(window.countdownInterval);
            window.countdownInterval = setInterval(() => {
                const distance = targetDate - new Date().getTime();
                const el = document.getElementById('countdown-container');
                if (!el) { clearInterval(window.countdownInterval); return; }
                if (distance <= 0) {
                    el.innerHTML = '<div class="countdown" style="margin:0; padding:8px 15px; font-size:1rem;">⚽ 比赛已开始，正在刷新...</div>';
                    clearInterval(window.countdownInterval);
                    loadData();  // 比赛开始, 自动拉取最新数据
                    return;
                }
                const h = Math.floor(distance / (1000 * 60 * 60));
                const m = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                const s = Math.floor((distance % (1000 * 60)) / 1000);
                const pad = n => String(n).padStart(2, '0');
                el.innerHTML = '<div class="countdown" style="margin:0; padding:8px 15px; font-size:1rem;">'
                    + '下场开赛：' + pad(h) + ':' + pad(m) + ':' + pad(s)
                    + '</div>';
            }, 1000);
        }
    }

    matches.forEach(m => {
        const matchDate = new Date(m.match_time_utc);
        const localDateStr = matchDate.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' });
        const localTimeStr = matchDate.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        const bjTimeStr = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(matchDate);

        const streams = globalData.broadcasts[m.id] || [];
        let streamsHTML = streams.map(b => `<a href="${esc(b.stream_url)}" target="_blank" class="player-chip">&#x1F3A5; ${esc(b.platform_name)}</a>`).join('');

        let homeDisplayHTML = '', awayDisplayHTML = '';
        // Player chip helper: PES-style ability badge + Chinese/English name
        function playerChipHtml(pid, isStarter) {
            var p = globalData.players[pid];
            if (!p) return '';
            var rating = globalData.playerRatings[pid] || 0;
            // PES-style gradient + tiered glow intensity
            var r1, g1, b1, r2, g2, b2, glowColor, glowSpread, innerGlow;
            if (rating >= 85) {
                r1=0;g1=220;b1=90; r2=0;g2=170;b2=55;
                glowColor='rgba(0,255,100,0.9)'; glowSpread='10px'; innerGlow='rgba(255,255,255,0.35)';
            } else if (rating >= 75) {
                r1=0;g1=230;b1=190; r2=0;g2=185;b2=145;
                glowColor='rgba(0,230,190,0.5)'; glowSpread='6px'; innerGlow='rgba(255,255,255,0.25)';
            } else if (rating >= 65) {
                r1=255;g1=185;b1=0; r2=220;g2=140;b2=0;
                glowColor='rgba(255,185,0,0.25)'; glowSpread='3px'; innerGlow='rgba(255,255,255,0.18)';
            } else if (rating >= 55) {
                r1=240;g1=120;b1=0; r2=190;g2=85;b2=0;
                glowColor='rgba(240,120,0,0.12)'; glowSpread='2px'; innerGlow='rgba(255,255,255,0.1)';
            } else {
                r1=180;g1=55;b1=55; r2=140;g2=35;b2=35;
                glowColor='rgba(180,55,55,0.06)'; glowSpread='1px'; innerGlow='rgba(255,255,255,0.05)';
            }
            var badgeGradient = 'linear-gradient(135deg, rgb('+r1+','+g1+','+b1+'), rgb('+r2+','+g2+','+b2+'))';
            var starterClass = isStarter ? ' starter' : '';
            return '<span class="player-chip' + starterClass + '" onclick="showPlayer(' + pid + ')" style="position:relative;padding-right:38px;">'
                + '<span style="position:absolute;top:-4px;right:-4px;width:30px;height:30px;'
                + 'background:' + badgeGradient + ';'
                + 'clip-path:polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%);'
                + 'display:flex;align-items:center;justify-content:center;'
                + 'box-shadow:0 0 ' + glowSpread + ' ' + glowColor + ',inset 0 1px 0 ' + innerGlow + ';'
                + '">'
                + '<span style="color:#fff;font-size:0.62rem;font-weight:900;text-shadow:0 1px 2px rgba(0,0,0,0.5);line-height:1;">' + (rating || '?') + '</span>'
                + '</span>'
                + '<div style="line-height:1.2;">'
                + '<span style="font-size:0.85rem;">' + esc(p.name_zh) + '</span>'
                + '<br><span style="font-size:0.65rem;color:var(--text-muted);">' + esc(p.name_en) + '</span>'
                + '</div></span>';
        }
        // Always show player chips: prefer lineups if available, fallback to squads
        let homeLineupStr = m.home_lineup.map(item => playerChipHtml(item.id, item.is_starter)).join('');
        let awayLineupStr = m.away_lineup.map(item => playerChipHtml(item.id, item.is_starter)).join('');
        let homeSquadStr = m.home_squad.map(pid => playerChipHtml(pid, false)).join('');
        let awaySquadStr = m.away_squad.map(pid => playerChipHtml(pid, false)).join('');

        if (m.status === 'upcoming') {
            // Upcoming matches: show squads
            homeDisplayHTML = `<h4>26人大名单</h4>${homeSquadStr || '大名单未公布'}`;
            awayDisplayHTML = `<h4>26人大名单</h4>${awaySquadStr || '大名单未公布'}`;
        } else if (homeLineupStr && awayLineupStr) {
            // Live/finished with lineups: show lineups
            homeDisplayHTML = `<h4>首发及替补阵容</h4>${homeLineupStr}`;
            awayDisplayHTML = `<h4>首发及替补阵容</h4>${awayLineupStr}`;
        } else {
            // Live/finished without lineups: fallback to squads with a note
            homeDisplayHTML = `<h4>26人大名单 <span style="font-size:0.75rem;color:var(--text-muted);font-weight:normal;">(阵容待公布)</span></h4>${homeSquadStr || '大名单未公布'}`;
            awayDisplayHTML = `<h4>26人大名单 <span style="font-size:0.75rem;color:var(--text-muted);font-weight:normal;">(阵容待公布)</span></h4>${awaySquadStr || '大名单未公布'}`;
        }

        let scoreHTML = `<div class="vs">VS</div>`;
        if(m.status === 'live' || m.status === 'finished') {
            scoreHTML = `<span>${m.home_score}</span> <span style="font-size:1.5rem;color:var(--text-muted)">-</span> <span>${m.away_score}</span>`;
        }

        const card = document.createElement('div');
        card.className = 'match-card';
        card.innerHTML = `
            <div class="match-header">
                <div class="time-box">
                    <div>📅 ${localDateStr} • ${localTimeStr} (本地)</div>
                    <div class="bj-time">🇨🇳 ${bjTimeStr} (北京时间)</div>
                </div>
                <div class="status-badge status-${m.status}">${statusMap[m.status]}</div>
                <div>${esc(m.group_stage)}</div>
            </div>
            <div class="teams-container">
                <div class="team" style="cursor:pointer;" onclick="showTeam(${m.home_team_id})">
                    <img src="${m.home_flag}">
                    <h3 style="margin-bottom: 5px; transition: color 0.2s;" onmouseover="this.style.color='var(--accent-blue)'" onmouseout="this.style.color=''"> ${esc(m.home_name_zh)}</h3>
                    <div style="font-size:0.8rem;color:var(--text-muted)">${esc(m.home_name)}</div>
                </div>
                <div class="score">${scoreHTML}</div>
                <div class="team" style="cursor:pointer;" onclick="showTeam(${m.away_team_id})">
                    <img src="${m.away_flag}">
                    <h3 style="margin-bottom: 5px; transition: color 0.2s;" onmouseover="this.style.color='var(--accent-blue)'" onmouseout="this.style.color=''"> ${esc(m.away_name_zh)}</h3>
                    <div style="font-size:0.8rem;color:var(--text-muted)">${esc(m.away_name)}</div>
                </div>
            </div>
            <div class="lineups">
                <div class="lineup-col">${homeDisplayHTML}</div>
                <div class="lineup-col" style="text-align:right">${awayDisplayHTML}</div>
            </div>
            ${ streamsHTML ? `<div style="margin-top:15px;border-top:1px solid rgba(255,255,255,0.05);padding-top:15px;"><strong>官方直播：</strong> ${streamsHTML}</div>` : '' }
        `;
        container.appendChild(card);
    });
}

function renderTeams() {
    const container = document.getElementById('teams-container');
    container.innerHTML = Object.values(globalData.teams).map(t => `
        <div class="team-card" style="cursor:pointer;" onclick="showTeam(${t.id})">
            <span class="group-badge" style="background:rgba(255,255,255,0.1);padding:4px 10px;border-radius:12px;font-size:0.8rem;display:inline-block;margin-bottom:10px;">${esc(t.group_name)}</span><br>
            <img src="${esc(t.flag_url)}">
            <h3 style="margin-bottom: 5px; transition: color 0.2s;" onmouseover="this.style.color='var(--accent-blue)'" onmouseout="this.style.color=''">${esc(t.name_zh)}</h3>
            <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:10px;">${esc(t.name)}</div>
            <div style="font-size:0.85rem;color:var(--accent-green)">点击查看百科 & 战绩 ➔</div>
        </div>
    `).join('');
}

function renderStandings() {
    const container = document.getElementById('standings-container');
    let groups = {};
    Object.values(globalData.teams).forEach(t => {
        const g = t.group_name;
        if(!g) return;
        if(!groups[g]) groups[g] = [];
        groups[g].push({id: t.id, name: t.name_zh, flag: t.flag_url, p:0, w:0, d:0, l:0, gf:0, ga:0, gd:0, pts:0});
    });
    
    const validGroups = ['A','B','C','D','E','F','G','H','I','J','K','L'];
    globalData.matches.forEach(m => {
        if(m.status !== 'finished' || !validGroups.includes(m.group_stage)) return;
        const g = m.group_stage;
        if(!groups[g]) return;
        let hTeam = groups[g].find(x => x.id === m.home_team_id);
        let aTeam = groups[g].find(x => x.id === m.away_team_id);
        
        if (hTeam && aTeam) {
            hTeam.p++; aTeam.p++;
            hTeam.gf += m.home_score; hTeam.ga += m.away_score;
            aTeam.gf += m.away_score; aTeam.ga += m.home_score;
            hTeam.gd = hTeam.gf - hTeam.ga; aTeam.gd = aTeam.gf - aTeam.ga;
            if(m.home_score > m.away_score) { hTeam.w++; hTeam.pts+=3; aTeam.l++; }
            else if(m.home_score < m.away_score) { aTeam.w++; aTeam.pts+=3; hTeam.l++; }
            else { hTeam.d++; aTeam.d++; hTeam.pts++; aTeam.pts++; }
        }
    });

    let html = '';
    Object.keys(groups).sort().forEach(g_name => {
        const sorted = groups[g_name].sort((a,b) => b.pts - a.pts || b.gd - a.gd || b.gf - a.gf);
        let rows = sorted.map((t, idx) => {
            let bg = idx < 2 ? "rgba(0,255,135,0.1)" : "transparent";
            return `
            <tr style="background: ${bg}; border-bottom: 1px solid rgba(255,255,255,0.05);">
                <td style="padding: 12px;">${idx+1}</td>
                <td style="padding: 12px; display:flex; align-items:center; gap:10px;"><img src="${esc(t.flag)}" style="width:24px; border-radius:4px;"> ${esc(t.name)}</td>
                <td style="padding: 12px;">${t.p}</td>
                <td style="padding: 12px;">${t.w}</td>
                <td style="padding: 12px;">${t.d}</td>
                <td style="padding: 12px;">${t.l}</td>
                <td style="padding: 12px;">${t.gf}</td>
                <td style="padding: 12px;">${t.ga}</td>
                <td style="padding: 12px;">${t.gd}</td>
                <td style="padding: 12px; font-weight:bold; color:var(--accent-green)">${t.pts}</td>
            </tr>`;
        }).join('');
        html += `
        <div class="match-card" style="margin-bottom: 30px;">
            <h3 style="margin-top:0; color:var(--accent-blue)">${esc(g_name)}</h3>
            <table style="width:100%; border-collapse: collapse; text-align: left;">
                <tr style="color:var(--text-muted); font-size:0.9rem; border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="padding: 10px;">排名</th><th style="padding: 10px;">球队</th><th style="padding: 10px;">场次</th>
                    <th style="padding: 10px;">胜</th><th style="padding: 10px;">平</th><th style="padding: 10px;">负</th>
                    <th style="padding: 10px;">进</th><th style="padding: 10px;">失</th><th style="padding: 10px;">净</th><th style="padding: 10px;">积分</th>
                </tr>
                ${rows}
            </table>
        </div>`;
    });
    container.innerHTML = html;
}

function renderScorers() {
    const container = document.getElementById('scorers-container');
    const scorers = Object.values(globalData.players).filter(p => p.tournament_goals > 0).sort((a,b) => b.tournament_goals - a.tournament_goals);
    
    container.innerHTML = scorers.map((p, idx) => {
        const avatar = p.profile_url && p.profile_url !== '#' ? p.profile_url : '';
        const imgTag = avatar 
            ? `<img src="${esc(avatar)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" style="width:44px; height:44px; border-radius:50%; object-fit:cover; border:2px solid rgba(255,255,255,0.15); background:rgba(255,255,255,0.05);">
               <div style="display:none; width:44px; height:44px; border-radius:50%; background:rgba(255,255,255,0.08); align-items:center; justify-content:center; font-size:1.2rem;">⚽</div>` 
            : `<div style="width:44px; height:44px; border-radius:50%; background:rgba(255,255,255,0.08); display:flex; align-items:center; justify-content:center; font-size:1.2rem;">⚽</div>`;
        var team = globalData.teams[p.team_id];
        var teamName = team ? team.name_zh : '';
        return `
        <div onclick="showPlayer(${p.id})" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; padding: 12px 15px; border-bottom: 1px solid rgba(255,255,255,0.05); background: var(--card-bg); transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.08)'" onmouseout="this.style.background='var(--card-bg)'">
            <div style="display:flex; align-items:center; gap:15px;">
                <div style="font-size:1.3rem; font-weight:bold; width:28px; color:var(--text-muted); text-align:center;">${idx+1}</div>
                ${imgTag}
                <div>
                    <div style="font-weight:bold; font-size:0.95rem;">${esc(p.name_zh)} <span style="font-size:0.7rem; color:var(--text-muted);">${esc(teamName)}</span></div>
                    <div style="font-size:0.75rem; color:var(--text-muted)">${esc(p.name_en)}</div>
                </div>
            </div>
            <div style="font-size:1.8rem; font-weight:900; color:var(--accent-green);">${p.tournament_goals}</div>
        </div>`;
    }).join('');
}

function renderBracket() {
    const container = document.getElementById('bracket-container');
    const stages = ['1/16决赛', '1/8决赛', '1/4决赛', '半决赛', '季军赛', '决赛'];
    let html = '';
    stages.forEach(stage => {
        const smatches = globalData.matches.filter(m => m.group_stage === stage);
        html += `<div style='display:flex; flex-direction:column; justify-content:space-around; gap:20px; min-width:200px;'>
            <h3 style='text-align:center; color:var(--accent-blue); margin-bottom:10px;'>${esc(stage)}</h3>`;
        smatches.forEach(m => {
            const hs = m.home_score !== null ? m.home_score : '-';
            const aS = m.away_score !== null ? m.away_score : '-';
            const color = m.status === 'live' ? "var(--accent-green)" : "inherit";
            const bg = m.status === 'live' ? "rgba(0, 255, 135, 0.1)" : "var(--card-bg)";
            // Show knockout labels for TBD teams, team names otherwise
            var homeDisplay = (m.home_name_zh === '待定' && m.home_label) ? m.home_label : m.home_name_zh;
            var awayDisplay = (m.away_name_zh === '待定' && m.away_label) ? m.away_label : m.away_name_zh;
            var labelHtml = (m.home_label && m.away_label && m.home_name_zh === '待定')
                ? '<div style=\"font-size:0.7rem; color:var(--text-muted); text-align:center; margin-bottom:4px; padding:3px 8px; background:rgba(0,240,255,0.05); border-radius:6px;\">' + esc(m.home_label) + ' vs ' + esc(m.away_label) + '</div>'
                : '';
            html += `
            <div class="match-card" style="padding: 10px 15px; margin-bottom:0; display:flex; flex-direction:column; gap:10px; border-color:${color}; background:${bg};">
                ${labelHtml}
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.9rem"><img src="${esc(m.home_flag)}" style="width:18px;vertical-align:middle;border-radius:2px;"> ${esc(homeDisplay)}</span>
                    <span style="font-weight:bold">${hs}</span>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.9rem"><img src="${esc(m.away_flag)}" style="width:18px;vertical-align:middle;border-radius:2px;"> ${esc(awayDisplay)}</span>
                    <span style="font-weight:bold">${aS}</span>
                </div>
            </div>`;
        });
        html += "</div>";
    });
    container.innerHTML = html;
}

function renderPowerRanking() {
    var ranking = globalData.powerRanking;
    var container = document.getElementById('power-ranking-container');
    if (!container) return;
    if (!ranking || ranking.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:50px;color:var(--text-muted);">暂无夺冠概率数据</div>';
        return;
    }

    var weightNote = '';
    var totalPlayed = 0;
    for (var i = 0; i < ranking.length; i++) { totalPlayed += (ranking[i].played || 0); }

    var html = '<div class="match-card" style="overflow-x:auto;padding:0;">';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">';
    html += '<thead><tr style="color:var(--text-muted);border-bottom:2px solid rgba(255,255,255,0.1);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.5px;">';
    html += '<th style="padding:12px 8px;text-align:center;min-width:40px;">#</th>';
    html += '<th style="padding:12px 8px;text-align:left;min-width:160px;">球队</th>';
    html += '<th style="padding:12px 8px;text-align:center;min-width:50px;">ELO</th>';
    html += '<th style="padding:12px 8px;text-align:center;min-width:60px;">历史<br>动量</th>';
    html += '<th style="padding:12px 8px;text-align:center;min-width:50px;">身价</th>';
    html += '<th style="padding:12px 8px;text-align:center;min-width:50px;">FIFA</th>';
    html += '<th style="padding:12px 8px;text-align:center;min-width:50px;">底蕴</th>';
    html += '<th style="padding:12px 8px;text-align:left;min-width:140px;">夺冠概率</th>';
    html += '</tr></thead><tbody>';

    for (var i = 0; i < ranking.length; i++) {
        var r = ranking[i];
        var medalBorder = '';
        var rowBg = '';
        if (r.rank === 1) { medalBorder = 'border-left:3px solid #FFD700;'; rowBg = 'background:rgba(255,215,0,0.08);'; }
        else if (r.rank === 2) { medalBorder = 'border-left:3px solid #C0C0C0;'; rowBg = 'background:rgba(192,192,192,0.06);'; }
        else if (r.rank === 3) { medalBorder = 'border-left:3px solid #CD7F32;'; rowBg = 'background:rgba(205,127,50,0.06);'; }

        var tierTag = '';
        var tierColor = 'rgba(255,255,255,0.15)';
        if (r.tier === 'Elite') tierColor = 'rgba(0,255,135,0.2)';
        else if (r.tier === 'Contender') tierColor = 'rgba(0,240,255,0.15)';
        else if (r.tier === 'Dark Horse') tierColor = 'rgba(255,165,0,0.15)';
        tierTag = '<span style="display:inline-block;margin-left:6px;padding:1px 8px;border-radius:10px;font-size:0.65rem;background:' + tierColor + ';color:var(--text-muted);vertical-align:middle;">' + esc(r.tier) + '</span>';

        var probPct = r.championship_probability;
        var probBar = '';
        var probColor = probPct > 12 ? 'linear-gradient(90deg,var(--accent-green),var(--accent-blue))'
            : probPct > 4 ? 'linear-gradient(90deg,rgba(0,255,135,0.6),rgba(0,240,255,0.4))'
            : 'rgba(255,255,255,0.15)';
        probBar = '<div style="flex:1;height:6px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;margin:0 10px;">'
            + '<div style="width:' + Math.max(probPct * 2.5, 0.5) + '%;height:100%;background:' + probColor + ';border-radius:3px;transition:width 0.5s;"></div></div>';

        var rowStyle = medalBorder + rowBg;
        if (r.eliminated) {
            rowStyle += 'opacity:0.35;';
        }
        html += '<tr style="' + rowStyle + 'border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.2s;" onmouseover="if(!' + (r.eliminated ? 'true' : 'false') + ')this.style.background=\'rgba(255,255,255,0.06)\'" onmouseout="this.style.background=\'' + (r.rank <= 3 ? rowBg : '') + '\'" onclick="showTeam(' + r.team_id + ')">';
        html += '<td style="padding:10px 8px;text-align:center;font-weight:700;font-size:1.1rem;">' + r.rank + '</td>';
        html += '<td style="padding:10px 8px;display:flex;align-items:center;gap:8px;">';
        html += '<img src="' + esc(r.flag_url) + '" style="width:28px;height:19px;border-radius:2px;flex-shrink:0;">';
        html += '<span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(r.name_zh) + '</span>';
        html += tierTag;
        if (r.eliminated) html += '<span style="color:var(--accent-red);font-size:0.65rem;margin-left:4px;">已淘汰</span>';
        html += '</td>';
        html += '<td style="padding:10px 8px;text-align:center;color:var(--text-muted);">' + (r.elo_rating || '-') + '</td>';
        // Historical momentum score (0-10, color coded)
        var histScore = r.hist_momentum_score || 0;
        var histColor = histScore > 7 ? 'var(--accent-green)' : histScore > 3 ? 'var(--accent-blue)' : 'var(--text-muted)';
        html += '<td style="padding:10px 8px;text-align:center;color:' + histColor + ';">' + histScore.toFixed(1) + '</td>';
        // Market value score
        var mvScore = r.market_value_score || 0;
        var mvColor = mvScore > 7 ? 'var(--accent-green)' : mvScore > 3 ? 'var(--accent-blue)' : 'var(--text-muted)';
        html += '<td style="padding:10px 8px;text-align:center;color:' + mvColor + ';">' + mvScore.toFixed(1) + '</td>';
        // FIFA rank score
        var fifaScore = r.fifa_rank_score || 0;
        var fifaColor = fifaScore > 8 ? 'var(--accent-green)' : fifaScore > 5 ? 'var(--accent-blue)' : 'var(--text-muted)';
        html += '<td style="padding:10px 8px;text-align:center;color:' + fifaColor + ';">' + fifaScore.toFixed(1) + '</td>';
        html += '<td style="padding:10px 8px;text-align:center;color:var(--text-muted);font-size:0.8rem;">' + (r.history_badge || '-') + '</td>';
        html += '<td style="padding:10px 8px;">';
        html += '<div style="display:flex;align-items:center;">';
        html += '<span style="min-width:50px;text-align:right;font-weight:700;' + (probPct > 10 ? 'color:var(--accent-green);' : probPct > 0 ? 'color:var(--text-muted);' : 'color:var(--accent-red);') + '">' + (probPct > 0 ? probPct.toFixed(1) + '%' : '0%') + '</span>';
        html += probBar;
        html += '</div>';
        html += '</td>';
        html += '</tr>';
    }
    html += '</tbody></table></div>';
    container.innerHTML = html;
}

// ── Historical Champions Data ──────────────────────────────────────────
var HISTORY_DATA = [
    {
        year: 2022, host: '卡塔尔',
        champion: { name: '阿根廷', name_en: 'Argentina', flag: 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Flag_of_Argentina.svg' },
        runnerUp: { name: '法国', name_en: 'France', flag: 'https://upload.wikimedia.org/wikipedia/en/c/c3/Flag_of_France.svg' },
        third:    { name: '克罗地亚', name_en: 'Croatia', flag: 'https://upload.wikimedia.org/wikipedia/commons/1/1b/Flag_of_Croatia.svg' },
        fourth:   { name: '摩洛哥', name_en: 'Morocco', flag: 'https://upload.wikimedia.org/wikipedia/commons/2/2c/Flag_of_Morocco.svg' },
        finalScore: '3-3 (4-2 P)',
        goldenBall: '利昂内尔·梅西',
        goldenBoot: '基利安·姆巴佩 (8球)',
    },
    {
        year: 2018, host: '俄罗斯',
        champion: { name: '法国', name_en: 'France', flag: 'https://upload.wikimedia.org/wikipedia/en/c/c3/Flag_of_France.svg' },
        runnerUp: { name: '克罗地亚', name_en: 'Croatia', flag: 'https://upload.wikimedia.org/wikipedia/commons/1/1b/Flag_of_Croatia.svg' },
        third:    { name: '比利时', name_en: 'Belgium', flag: 'https://upload.wikimedia.org/wikipedia/commons/6/65/Flag_of_Belgium.svg' },
        fourth:   { name: '英格兰', name_en: 'England', flag: 'https://upload.wikimedia.org/wikipedia/en/b/be/Flag_of_England.svg' },
        finalScore: '4-2',
        goldenBall: '卢卡·莫德里奇',
        goldenBoot: '哈里·凯恩 (6球)',
    },
    {
        year: 2014, host: '巴西',
        champion: { name: '德国', name_en: 'Germany', flag: 'https://upload.wikimedia.org/wikipedia/en/b/ba/Flag_of_Germany.svg' },
        runnerUp: { name: '阿根廷', name_en: 'Argentina', flag: 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Flag_of_Argentina.svg' },
        third:    { name: '荷兰', name_en: 'Netherlands', flag: 'https://upload.wikimedia.org/wikipedia/commons/2/20/Flag_of_the_Netherlands.svg' },
        fourth:   { name: '巴西', name_en: 'Brazil', flag: 'https://upload.wikimedia.org/wikipedia/en/0/05/Flag_of_Brazil.svg' },
        finalScore: '1-0 (OT)',
        goldenBall: '利昂内尔·梅西',
        goldenBoot: '哈梅斯·罗德里格斯 (6球)',
    },
    {
        year: 2010, host: '南非',
        champion: { name: '西班牙', name_en: 'Spain', flag: 'https://upload.wikimedia.org/wikipedia/commons/9/9a/Flag_of_Spain.svg' },
        runnerUp: { name: '荷兰', name_en: 'Netherlands', flag: 'https://upload.wikimedia.org/wikipedia/commons/2/20/Flag_of_the_Netherlands.svg' },
        third:    { name: '德国', name_en: 'Germany', flag: 'https://upload.wikimedia.org/wikipedia/en/b/ba/Flag_of_Germany.svg' },
        fourth:   { name: '乌拉圭', name_en: 'Uruguay', flag: 'https://upload.wikimedia.org/wikipedia/commons/f/fe/Flag_of_Uruguay.svg' },
        finalScore: '1-0 (OT)',
        goldenBall: '迭戈·弗兰',
        goldenBoot: '托马斯·穆勒 (5球)',
    },
    {
        year: 2006, host: '德国',
        champion: { name: '意大利', name_en: 'Italy', flag: 'https://upload.wikimedia.org/wikipedia/en/0/03/Flag_of_Italy.svg' },
        runnerUp: { name: '法国', name_en: 'France', flag: 'https://upload.wikimedia.org/wikipedia/en/c/c3/Flag_of_France.svg' },
        third:    { name: '德国', name_en: 'Germany', flag: 'https://upload.wikimedia.org/wikipedia/en/b/ba/Flag_of_Germany.svg' },
        fourth:   { name: '葡萄牙', name_en: 'Portugal', flag: 'https://upload.wikimedia.org/wikipedia/commons/5/5c/Flag_of_Portugal.svg' },
        finalScore: '1-1 (5-3 P)',
        goldenBall: '齐内丁·齐达内',
        goldenBoot: '米罗斯拉夫·克洛泽 (5球)',
    },
    {
        year: 2002, host: '韩日',
        champion: { name: '巴西', name_en: 'Brazil', flag: 'https://upload.wikimedia.org/wikipedia/en/0/05/Flag_of_Brazil.svg' },
        runnerUp: { name: '德国', name_en: 'Germany', flag: 'https://upload.wikimedia.org/wikipedia/en/b/ba/Flag_of_Germany.svg' },
        third:    { name: '土耳其', name_en: 'Turkey', flag: 'https://upload.wikimedia.org/wikipedia/commons/b/b4/Flag_of_Turkey.svg' },
        fourth:   { name: '韩国', name_en: 'South Korea', flag: 'https://upload.wikimedia.org/wikipedia/commons/0/09/Flag_of_South_Korea.svg' },
        finalScore: '2-0',
        goldenBall: '奥利弗·卡恩',
        goldenBoot: '罗纳尔多 (8球)',
    },
];

function renderHistory() {
    var container = document.getElementById('history-container');
    if (!container) return;
    var html = '';
    
    for (var i = 0; i < HISTORY_DATA.length; i++) {
        var wc = HISTORY_DATA[i];
        // Medal row helper
        function medalRow(label, team, medalClass, medalEmoji) {
            return '<div class="history-medal-row" style="display:flex;align-items:center;gap:12px;padding:8px 12px;margin-bottom:4px;border-radius:8px;background:' + medalClass + ';">'
                + '<span style="font-size:1.1rem;width:24px;text-align:center;">' + medalEmoji + '</span>'
                + '<img src="' + esc(team.flag) + '" style="width:28px;height:19px;border-radius:2px;flex-shrink:0;">'
                + '<span style="font-weight:600;color:var(--text-main);">' + esc(team.name) + '</span>'
                + '<span style="font-size:0.75rem;color:var(--text-muted);margin-left:auto;">' + esc(label) + '</span>'
                + '</div>';
        }

        html += '<div class="match-card" style="margin-bottom:20px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">';
        html += '<h3 style="margin:0;color:var(--accent-green);font-size:1.3rem;">' + wc.year + ' ' + esc(wc.host) + '</h3>';
        html += '<span style="font-size:0.75rem;color:var(--text-muted);background:rgba(255,255,255,0.05);padding:4px 12px;border-radius:12px;">决赛 ' + esc(wc.finalScore) + '</span>';
        html += '</div>';

        // Champion - Gold
        html += medalRow('冠军', wc.champion, 'rgba(255,215,0,0.12)', '🥇');
        // Runner-up - Silver
        html += medalRow('亚军', wc.runnerUp, 'rgba(192,192,192,0.08)', '🥈');
        // Third - Bronze
        html += medalRow('季军', wc.third, 'rgba(205,127,50,0.08)', '🥉');
        // Fourth
        html += medalRow('殿军', wc.fourth, 'rgba(255,255,255,0.03)', '4️⃣');

        html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:20px;font-size:0.75rem;color:var(--text-muted);">';
        html += '<span>🏅 金球奖: ' + esc(wc.goldenBall) + '</span>';
        html += '<span>⚽ 金靴奖: ' + esc(wc.goldenBoot) + '</span>';
        html += '</div>';
        html += '</div>';
    }
    container.innerHTML = html;
}

// Modals
window.showPlayer = function(pid) {
    const p = globalData.players[pid];
    if(!p) return;
    document.getElementById('modal-name').innerText = p.name_zh + ' (' + p.name_en + ')';
    document.getElementById('modal-sub').innerText = (posMap[p.position] || p.position) + ' • ' + p.jersey_number + '号';
    
    // Parse enriched description JSON from TheSportsDB
    var extra = {};
    var bioText = '';
    var wallpapers = [];
    var wikiUrl = '';
    try {
        extra = JSON.parse(p.description || '{}');
        // Prefer Wikipedia extract over TSD bio
        if (extra.wiki_extract) {
            bioText = extra.wiki_extract;
            wikiUrl = extra.wiki_url || '';
        } else if (extra.bio) {
            bioText = extra.bio.substring(0, 500) + '...';
        }
        if (extra.fanart) wallpapers.push({label:'海报', url:extra.fanart});
        if (extra.banner) wallpapers.push({label:'横幅', url:extra.banner});
        if (extra.fanart1) wallpapers.push({label:'壁纸1', url:extra.fanart1});
        if (extra.fanart2) wallpapers.push({label:'壁纸2', url:extra.fanart2});
    } catch(e) {}
    
    // Build description HTML
    var descParts = [];
    if (extra.full_name) descParts.push('<strong>全名：</strong>' + esc(extra.full_name));
    if (extra.birth) descParts.push('<strong>出生：</strong>' + esc(extra.birth) + ' • ' + esc(extra.birth_place || ''));
    if (extra.height) descParts.push('<strong>身高/体重：</strong>' + esc(extra.height) + ' / ' + esc(extra.weight || ''));
    if (extra.nationality) descParts.push('<strong>国籍：</strong>' + esc(extra.nationality));
    if (extra.team) descParts.push('<strong>效力球队：</strong>' + esc(extra.team));
    if (extra.position) descParts.push('<strong>位置：</strong>' + esc(extra.position));
    if (bioText) descParts.push('<br><strong>简介：</strong><br>' + esc(bioText));
    if (wikiUrl) descParts.push('<a href=\"' + esc(wikiUrl) + '\" target=\"_blank\" style=\"color:var(--accent-green);\">📖 Wikipedia 全文</a>');
    if (extra.instagram) descParts.push('<a href=\"https://instagram.com/' + esc(extra.instagram) + '\" target=\"_blank\" style=\"color:var(--accent-blue);\">📷 Instagram</a>');
    document.getElementById('modal-desc').innerHTML = descParts.join('<br>') || '暂无详细信息';
    
    // Avatar image
    const imgEl = document.getElementById('modal-img');
    imgEl.style.borderRadius = '50%';
    if (p.profile_url && p.profile_url !== '#') {
        imgEl.src = p.profile_url;
        imgEl.style.display = 'block';
    } else {
        imgEl.style.display = 'none';
    }
    
    // Wallpaper links
    var statsHtml = wallpapers.length > 0 ? '<strong>📸 精美大图（点击新窗口打开做壁纸）：</strong><br>' : '';
    wallpapers.forEach(function(w) {
        statsHtml += '<a href=\"' + esc(w.url) + '\" target=\"_blank\" style=\"display:inline-block; margin:6px 8px 6px 0; padding:6px 14px; background:rgba(0,240,255,0.1); border:1px solid rgba(0,240,255,0.3); border-radius:8px; color:var(--accent-blue); font-size:0.85rem; text-decoration:none; transition:background 0.2s;\" onmouseover=\"this.style.background=\'rgba(0,240,255,0.25)\'\" onmouseout=\"this.style.background=\'rgba(0,240,255,0.1)\'\">🖼️ ' + esc(w.label) + '</a>';
    });
    
    // Also show old history_stats if present
    try {
        const stats = JSON.parse(p.history_stats);
        var hasStats = false;
        for(let key in stats) {
            if (!hasStats) { statsHtml += '<br><br><strong>历史数据：</strong><br>'; hasStats = true; }
            let displayKey = statsI18n[key] || key.toUpperCase();
            let val = stats[key] === true ? '是' : (stats[key] === false ? '否' : stats[key]);
            statsHtml += '<div style=\"margin-bottom:4px; font-size:0.85rem;\"><strong>' + esc(displayKey) + ':</strong> ' + esc(val) + '</div>';
        }
    } catch(e) {}
    document.getElementById('modal-stats').innerHTML = statsHtml || '暂无额外数据';
    document.getElementById('info-modal').style.display = 'flex';
};

window.showTeam = function(tid) {
    const t = globalData.teams[tid];
    if(!t) return;
    document.getElementById('modal-name').innerText = t.name_zh + ' (' + t.name_en + ')';
    document.getElementById('modal-sub').innerText = '世界杯入围球队 • ' + t.group_name;

    var coachText = t.coach || '暂无';
    var descText = t.description || '暂无详细介绍';
    var descHtml = '<strong>现任主教练：</strong> ' + esc(coachText) + '<br><br>';
    descHtml += '<strong>球队简介：</strong><br>' + esc(descText);
    document.getElementById('modal-desc').innerHTML = descHtml;
    
    const imgEl = document.getElementById('modal-img');
    if (t.flag_url) {
        imgEl.src = t.flag_url;
        imgEl.style.display = 'block';
        imgEl.style.borderRadius = '8px';
    } else {
        imgEl.style.display = 'none';
    }
    
    let statsHtml = '';
    try {
        const stats = JSON.parse(t.history_stats);
        if (stats && Object.keys(stats).length > 0) {
            for(let key in stats) {
                statsHtml += `<div style="margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:4px;"><strong>${esc(key)}:</strong> ${esc(stats[key])}</div>`;
            }
        }
    } catch(e) {}
    document.getElementById('modal-stats').innerHTML = statsHtml || '暂无历史战绩数据';
    document.getElementById('info-modal').style.display = 'flex';
};

// Initial load — reads settings from DB, starts timers
loadData().then(function() { loadPowerRanking(); loadPlayerRatings(); loadSettings(); });

// Refresh-interval input handler
document.addEventListener('DOMContentLoaded', function() {
    var inp = document.getElementById('refresh-interval-input');
    if (inp) {
        inp.addEventListener('change', function() {
            var val = parseInt(this.value) || 5;
            val = Math.max(1, Math.min(val, 60));
            this.value = val;
            saveRefreshInterval(val);
            startTimers(val);
        });
    }
});

function renderPlayerRatings() {
    var container = document.getElementById('player-ratings-container');
    if (!container) return;
    var ranking = globalData.playerRanking || [];
    if (!ranking.length) {
        container.innerHTML = '<div style="text-align:center;padding:50px;color:var(--text-muted);">评分数据加载中...</div>';
        return;
    }

    // Search / position filter
    var search = (document.getElementById('ratings-search') || {}).value || '';
    var posFilter = (document.getElementById('ratings-pos') || {}).value || '';
    var filtered = ranking.filter(function(p) {
        if (posFilter && p.position !== posFilter) return false;
        if (search) {
            var q = search.toLowerCase();
            return (p.name_zh && p.name_zh.toLowerCase().indexOf(q) >= 0)
                || (p.name_en && p.name_en.toLowerCase().indexOf(q) >= 0)
                || (p.team_name_zh && p.team_name_zh.toLowerCase().indexOf(q) >= 0);
        }
        return true;
    });

    // Update count
    var countEl = document.getElementById('ratings-count');
    if (countEl) countEl.textContent = '显示 ' + filtered.length + ' / ' + ranking.length + ' 名球员';

    var html = '<div class="match-card" style="overflow-x:auto;padding:0;">';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">';
    html += '<thead><tr style="color:var(--text-muted);border-bottom:2px solid rgba(255,255,255,0.1);font-size:0.7rem;text-transform:uppercase;letter-spacing:0.5px;">';
    html += '<th style="padding:10px 6px;text-align:center;min-width:30px;">#</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:50px;">评分</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:36px;"></th>';
    html += '<th style="padding:10px 8px;text-align:left;min-width:90px;">中文名</th>';
    html += '<th style="padding:10px 8px;text-align:left;min-width:100px;">英文名</th>';
    html += '<th style="padding:10px 6px;text-align:left;min-width:80px;">球队</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:40px;">位置</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:40px;">号码</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:40px;">进球</th>';
    html += '<th style="padding:10px 6px;text-align:center;min-width:40px;">助攻</th>';
    html += '</tr></thead><tbody>';

    for (var i = 0; i < filtered.length; i++) {
        var p = filtered[i];
        var rank = i + 1;

        // Rating badge color
        var r = p.rating || 0;
        var badgeColor, badgeGlow;
        if (r >= 85)       { badgeColor = '#00ff55'; badgeGlow = '0 0 10px rgba(0,255,100,0.9)'; }
        else if (r >= 75)  { badgeColor = '#00e6be'; badgeGlow = '0 0 6px rgba(0,230,190,0.5)'; }
        else if (r >= 65)  { badgeColor = '#ffb900'; badgeGlow = '0 0 3px rgba(255,185,0,0.25)'; }
        else if (r >= 55)  { badgeColor = '#cc8800'; badgeGlow = '0 0 2px rgba(200,140,0,0.15)'; }
        else               { badgeColor = '#aa4444'; badgeGlow = 'none'; }

        // Medal borders for top 3
        var rowStyle = '';
        if (rank === 1) rowStyle = 'border-left:3px solid #FFD700;background:rgba(255,215,0,0.06);';
        else if (rank === 2) rowStyle = 'border-left:3px solid #C0C0C0;background:rgba(192,192,192,0.04);';
        else if (rank === 3) rowStyle = 'border-left:3px solid #CD7F32;background:rgba(205,127,50,0.04);';

        // Avatar
        var avatarHtml = '';
        if (p.profile_url && p.profile_url !== '#') {
            avatarHtml = '<img src="' + esc(p.profile_url) + '" style="width:32px;height:32px;border-radius:50%;object-fit:cover;border:1px solid rgba(255,255,255,0.1);" onerror="this.style.display=\'none\'">';
        } else {
            avatarHtml = '<div style="width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.06);display:flex;align-items:center;justify-content:center;font-size:0.7rem;">' + (p.position || '?') + '</div>';
        }

        // Team flag
        var flagHtml = p.team_flag ? '<img src="' + esc(p.team_flag) + '" style="width:18px;height:12px;border-radius:2px;vertical-align:middle;margin-right:4px;">' : '';

        html += '<tr style="' + rowStyle + 'border-bottom:1px solid rgba(255,255,255,0.03);cursor:pointer;" onclick="showPlayer(' + p.player_id + ')" onmouseover="this.style.background=\'rgba(255,255,255,0.04)\'" onmouseout="this.style.background=\'' + (rank <= 3 ? (rowStyle.match(/background:[^;]+/) || [])[0] || '' : '') + '\'">';
        html += '<td style="padding:8px 6px;text-align:center;font-weight:700;font-size:0.9rem;">' + rank + '</td>';
        html += '<td style="padding:8px 6px;text-align:center;"><span style="display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;clip-path:polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%);background:rgba(255,255,255,0.08);color:' + badgeColor + ';font-weight:900;font-size:0.85rem;text-shadow:' + badgeGlow + ';">' + r + '</span></td>';
        html += '<td style="padding:8px 6px;text-align:center;">' + avatarHtml + '</td>';
        html += '<td style="padding:8px;font-weight:600;">' + esc(p.name_zh || '') + '</td>';
        html += '<td style="padding:8px;color:var(--text-muted);font-size:0.75rem;">' + esc(p.name_en || '') + '</td>';
        html += '<td style="padding:8px 6px;font-size:0.8rem;">' + flagHtml + esc(p.team_name_zh || '') + '</td>';
        html += '<td style="padding:8px 6px;text-align:center;font-size:0.75rem;color:var(--text-muted);">' + esc(p.position || '') + '</td>';
        html += '<td style="padding:8px 6px;text-align:center;color:var(--text-muted);">' + (p.jersey_number || '-') + '</td>';
        html += '<td style="padding:8px 6px;text-align:center;font-weight:600;' + (p.tournament_goals > 0 ? 'color:var(--accent-green);' : 'color:var(--text-muted);') + '">' + (p.tournament_goals || 0) + '</td>';
        html += '<td style="padding:8px 6px;text-align:center;' + (p.tournament_assists > 0 ? 'color:var(--accent-blue);' : 'color:var(--text-muted);') + '">' + (p.tournament_assists || 0) + '</td>';
        html += '</tr>';
    }
    html += '</tbody></table></div>';
    container.innerHTML = html;
}
