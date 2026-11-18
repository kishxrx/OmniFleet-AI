const $ = id => document.getElementById(id);
let current = null, lastState = null, map = null, mapConfig = null, tasking = false;
let sensorState = null, objectPlacement = false, movingObjectId = null, blackboxData = null, blackboxPlayTimer = null, blackboxReplayMarker = null, blackboxReplaySample = null;
let markers = new Map(), routes = new Map(), coverageLayers = new Map(), coverageDrawing = false, coveragePoints = [], coveragePreview = null, coveragePointLayers = [], layers = { routes: true, zones: true, labels: true, sensors: true, comms: false, objects: true, observations: true };
let overlays = { geofence: null, noGo: [], obstacles: [], obstacleLayers: new Map(), home: null };
let sensorMapLayers = { footprints: new Map(), comms: new Map(), objects: new Map(), observations: new Map() };
let swarmState = null, swarmConfigDirty = false;
const palette = { quadrotor: '#4f9877', 'fixed-wing': '#c18e43', ground_robot: '#7e8eae' };

const helpDialog = $('help-dialog');
$('help-open').addEventListener('click', () => helpDialog.showModal());
$('help-close').addEventListener('click', () => helpDialog.close());
helpDialog.addEventListener('click', event => {
  if (event.target === helpDialog) helpDialog.close();
  const jump = event.target.closest('[data-help-jump]');
  if (jump) { event.preventDefault(); helpDialog.close(); const target = document.querySelector(new URL(jump.href).hash); target?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
});


async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  let data = {}; try { data = await response.json(); } catch {}
  if (!response.ok) throw Error(data.detail || 'Request failed');
  return data;
}
function esc(t) { return String(t ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
function iconFor(v) { return v.kind === 'fixed-wing' ? '✈' : v.kind === 'ground_robot' ? '▣' : '✣'; }
function statusClass(v) { return v.failed || v.status === 'failed' ? 'failed' : ''; }
function localToLatLng(x, y) {
  const half = mapConfig.width_m / 2, origin = mapConfig.origin;
  const lat = origin.lat + ((y / 100 * mapConfig.width_m) - half) / 111320;
  const lon = origin.lon + ((x / 100 * mapConfig.width_m) - half) / (111320 * Math.cos(origin.lat * Math.PI / 180));
  return [lat, lon];
}
function wgs84ToLocalFallback(lat,lon) {
  const half=mapConfig.width_m/2, origin=mapConfig.origin;
  return {x:((lon-origin.lon)*111320*Math.cos(origin.lat*Math.PI/180)+half)/mapConfig.width_m*100,
    y:((lat-origin.lat)*111320+half)/mapConfig.width_m*100};
}
function vehicleIcon(v) {
  const cls = v.failed ? 'vehicle-marker marker-failed' : `vehicle-marker marker-${v.kind.replace('_','-')}`;
  const glyph = iconFor(v);
  return L.divIcon({ className: 'vehicle-icon-wrap', html: `<div class="${cls}"><span>${glyph}</span></div>`, iconSize: [34, 34], iconAnchor: [17, 17] });
}
function initMap() {
  const mapEl = $('map'), fallback = $('map-fallback');
  if (!window.L || !mapConfig) {
    mapEl.style.display = 'none'; fallback.style.display = 'block';
    $('map-tasking').disabled = false;
    $('map-tasking-status').textContent = 'OFFLINE BASEMAP';
    drawFallback(lastState?.fleet || []);
    fallback.addEventListener('click', handleFallbackClick);
    return;
  }
  map = L.map('map', { zoomControl: false, preferCanvas: true, minZoom: 12, maxZoom: 19, scrollWheelZoom: true });
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  const bounds = L.latLngBounds(mapConfig.bounds);
  map.fitBounds(bounds.pad(0.08));
  map.setMaxBounds(bounds.pad(0.7));
  overlays.geofence = L.polygon(mapConfig.geofence, { color: '#438b66', weight: 2, dashArray: '8 6', fillColor: '#73b28a', fillOpacity: 0.08, interactive: false }).addTo(map);
  mapConfig.no_go_zones.forEach((polygon, i) => {
    const layer = L.polygon(polygon, { color: '#c56f5e', weight: 1.5, dashArray: '5 5', fillColor: '#d97c68', fillOpacity: 0.23, interactive: false });
    overlays.noGo.push(layer); layer.addTo(map);
    if (layers.labels) layer.bindTooltip(`RESTRICTED ZONE ${i + 1}`, { permanent: true, direction: 'center', className: 'zone-label' });
  });
  (mapConfig.obstacles || []).forEach(obstacle => {
    const layer=L.polygon(obstacle.polygon,{color:'#766b59',weight:2,fillColor:'#897c68',fillOpacity:.42,interactive:false});
    overlays.obstacles.push(layer); overlays.obstacleLayers.set(obstacle.id, layer); layer.addTo(map);
    if(layers.labels) layer.bindTooltip(obstacle.label || 'SIMULATED OBSTACLE',{permanent:true,direction:'center',className:'zone-label'});
  });
  const home = localToLatLng(10, 10);
  overlays.home = L.marker(home, { icon: L.divIcon({ className: 'home-icon-wrap', html: '<div class="home-marker">⌂</div>', iconSize: [28, 28], iconAnchor: [14, 14] }) }).addTo(map).bindTooltip('BASE / ALPHA');
  map.on('click', handleMapClick);
  setTimeout(() => map.invalidateSize(), 120);
}
function updateMap(fleet, environment = {}) {
  if (!map) { drawFallback(fleet); return; }
  (environment.moving_obstacles || []).forEach(obstacle => {
    const layer=overlays.obstacleLayers.get(obstacle.id);
    if(layer) layer.setLatLngs(obstacle.polygon.map(([x,y])=>localToLatLng(x,y)));
  });
  const seen = new Set();
  for (const v of fleet) {
    seen.add(v.id);
    const ll = [v.latitude, v.longitude];
    const popup = `<div class="map-popup"><b>${esc(v.name)}</b><span>${esc(v.kind.replace('_',' '))} · ${esc(v.status)}</span><span>${v.latitude.toFixed(6)}, ${v.longitude.toFixed(6)}</span><span>Battery ${Math.round(v.battery_pct)}% · ${v.altitude_m.toFixed(0)} m</span></div>`;
    if (!markers.has(v.id)) markers.set(v.id, L.marker(ll, { icon: vehicleIcon(v), title: v.name }).addTo(map));
    markers.get(v.id).setLatLng(ll).setIcon(vehicleIcon(v)).bindPopup(popup);
    if (routes.has(v.id)) { map.removeLayer(routes.get(v.id)); routes.delete(v.id); }
    if (layers.routes && v.target_latitude != null) {
      const line = L.polyline([ll, [v.target_latitude, v.target_longitude]], { color: palette[v.kind] || '#4f9877', weight: 3, opacity: .82, dashArray: '8 7' }).addTo(map);
      routes.set(v.id, line);
    }
  }
  for (const [id, marker] of markers) if (!seen.has(id)) { map.removeLayer(marker); markers.delete(id); }
  if (overlays.geofence) overlays.geofence.setStyle({ opacity: layers.zones ? 1 : 0, fillOpacity: layers.zones ? .08 : 0 });
  overlays.noGo.forEach((layer, i) => {
    if (layers.zones) layer.addTo(map); else map.removeLayer(layer);
    if (layers.labels && !layer.getTooltip()) layer.bindTooltip(`RESTRICTED ZONE ${i + 1}`, { permanent: true, direction: 'center', className: 'zone-label' });
    if (!layers.labels && layer.getTooltip()) layer.unbindTooltip();
  });
  overlays.obstacles.forEach(layer => {
    if(layers.zones) layer.addTo(map); else map.removeLayer(layer);
    if(layers.labels && !layer.getTooltip()) layer.bindTooltip('SIMULATED OBSTACLE',{permanent:true,direction:'center',className:'zone-label'});
    if(!layers.labels && layer.getTooltip()) layer.unbindTooltip();
  });
  if (overlays.home) { if (layers.labels) overlays.home.addTo(map); else map.removeLayer(overlays.home); }
  if (lastState) renderCoverageLayers(lastState.missions || []);
  if (sensorState) renderSensorMap(sensorState);
}
function renderCoverageLayers(missions) {
  if (!map) return;
  const wanted = new Set();
  missions.filter(m => m.coverage_polygon || (m.actions || []).some(a => a.route_points)).forEach(m => {
    if (m.coverage_polygon) {
      const key = `${m.id}:boundary`; wanted.add(key);
      const pts = m.coverage_polygon.map(p => [p.latitude, p.longitude]);
      if (!coverageLayers.has(key)) coverageLayers.set(key, L.polygon(pts, {color:'#568b68',weight:2,dashArray:'5 5',fillColor:'#75a983',fillOpacity:.07,interactive:false}).addTo(map));
      else coverageLayers.get(key).setLatLngs(pts);
    }
    (m.actions || []).filter(a => a.route_points).forEach((a,i) => {
      const key = `${m.id}:${a.vehicle_id}:${i}`; wanted.add(key);
      const pts = a.route_points.map(p => localToLatLng(p.x,p.y));
      const color = palette[(lastState.fleet.find(v=>v.id===a.vehicle_id)||{}).kind] || '#4f9877';
      if (!coverageLayers.has(key)) coverageLayers.set(key, L.polyline(pts,{color,weight:3,opacity:.8,dashArray:'4 5'}).addTo(map));
      else coverageLayers.get(key).setLatLngs(pts);
    });
  });
  for (const [key,layer] of coverageLayers) if (!wanted.has(key)) { map.removeLayer(layer); coverageLayers.delete(key); }
}
function drawCoveragePreview() {
  if (map) {
    if (coveragePreview) map.removeLayer(coveragePreview);
    coveragePointLayers.forEach(x=>map.removeLayer(x)); coveragePointLayers=[];
    const pts=coveragePoints;
    if (pts.length>=2) coveragePreview=L.polyline(pts,{color:'#b77c37',weight:3,dashArray:'6 5'}).addTo(map);
    pts.forEach((p,i)=>coveragePointLayers.push(L.circleMarker(p,{radius:5,color:'#fff',weight:2,fillColor:'#b77c37',fillOpacity:1}).addTo(map).bindTooltip(`P${i+1}`)));
  } else if (lastState) drawFallback(lastState.fleet);
  $('coverage-finish').disabled=coveragePoints.length<3;
  $('coverage-clear').disabled=coveragePoints.length===0;
  $('coverage-status').textContent=coverageDrawing?`${coveragePoints.length} boundary point(s) · click map to add points`:`${coveragePoints.length} boundary point(s) selected`;
}
function drawFallback(fleet) {
  const canvas = $('map-fallback'); if (!canvas) return;
  const ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#e9efe8'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = 'rgba(100,130,110,.17)'; ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 60) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,h); ctx.stroke(); }
  for (let y = 0; y < h; y += 60) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
  const X = x => x / 100 * w, Y = y => h - y / 100 * h;
  ctx.fillStyle = 'rgba(217,124,104,.18)'; ctx.fillRect(X(20),Y(82),X(42)-X(20),Y(62)-Y(82));
  ctx.fillStyle='rgba(137,124,104,.42)';ctx.strokeStyle='#766b59';ctx.lineWidth=2;ctx.fillRect(X(63),Y(76),X(72)-X(63),Y(66)-Y(76));ctx.strokeRect(X(63),Y(76),X(72)-X(63),Y(66)-Y(76));
  ctx.strokeStyle = '#438b66'; ctx.setLineDash([8,6]); ctx.lineWidth = 3; ctx.strokeRect(X(4),Y(96),X(92),Y(4)); ctx.setLineDash([]);
  if(coveragePoints.length){ctx.strokeStyle='#b77c37';ctx.lineWidth=3;ctx.setLineDash([7,5]);ctx.beginPath();coveragePoints.forEach((p,i)=>{const [lat,lon]=p;const q=wgs84ToLocalFallback(lat,lon);if(i===0)ctx.moveTo(X(q.x),Y(q.y));else ctx.lineTo(X(q.x),Y(q.y));});ctx.stroke();ctx.setLineDash([]);}
  (lastState?.missions||[]).filter(m=>m.coverage_polygon||(m.actions||[]).some(a=>a.route_points)).forEach(m=>{
    if(m.coverage_polygon?.length){const pts=m.coverage_polygon.map(p=>wgs84ToLocalFallback(p.latitude,p.longitude));ctx.strokeStyle='#b77c37';ctx.lineWidth=2;ctx.setLineDash([7,5]);ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(X(p.x),Y(p.y)):ctx.moveTo(X(p.x),Y(p.y)));ctx.closePath();ctx.stroke();ctx.setLineDash([]);}
    (m.actions||[]).filter(a=>a.route_points).forEach(a=>{const vehicle=(fleet||[]).find(v=>v.id===a.vehicle_id);ctx.strokeStyle=palette[vehicle?.kind]||'#4f9877';ctx.lineWidth=3;ctx.setLineDash([4,5]);ctx.beginPath();a.route_points.forEach((p,i)=>i?ctx.lineTo(X(p.x),Y(p.y)):ctx.moveTo(X(p.x),Y(p.y)));ctx.stroke();ctx.setLineDash([]);});
  });
  if (sensorState?.vehicles) {
    sensorState.vehicles.forEach(v => {
      const px=X(v.x), py=Y(v.y), unit=w/100;
      if (layers.sensors && v.sensor_enabled) { ctx.beginPath(); ctx.arc(px,py,(v.sensor_range_m/(mapConfig.width_m/100))*unit,0,Math.PI*2); ctx.fillStyle='rgba(87,145,112,.07)'; ctx.fill(); ctx.strokeStyle='rgba(73,132,96,.65)'; ctx.lineWidth=2; ctx.stroke(); }
      if (layers.comms) { ctx.beginPath(); ctx.arc(px,py,(v.comm_range_m/(mapConfig.width_m/100))*unit,0,Math.PI*2); ctx.strokeStyle='rgba(109,130,160,.62)'; ctx.lineWidth=1.5; ctx.setLineDash([7,6]); ctx.stroke(); ctx.setLineDash([]); }
    });
  }
  if (layers.objects) (sensorState?.objects||[]).forEach(o=>{const x=X(o.x),y=Y(o.y);ctx.fillStyle=o.visible?'#c58a3b':'#8c9690';ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,11,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle='#fff';ctx.font='bold 12px Arial';ctx.textAlign='center';ctx.fillText('◇',x,y+4);ctx.textAlign='left';});
  if (layers.observations) (sensorState?.observations||[]).slice(0,80).forEach(o=>{const x=X(o.x),y=Y(o.y);ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fillStyle=o.shared_status==='SHARED'?'#438c6b':'#ca8842';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();});
  if (blackboxReplaySample) { ctx.beginPath(); ctx.arc(X(blackboxReplaySample.x),Y(blackboxReplaySample.y),12,0,Math.PI*2); ctx.strokeStyle='#b27a36'; ctx.lineWidth=3; ctx.stroke(); }
  fleet.forEach(v => { const x=X(v.x), y=Y(v.y), c=palette[v.kind]||'#4f9877'; if(v.target_x!=null){ctx.strokeStyle=c;ctx.setLineDash([8,6]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(X(v.target_x),Y(v.target_y));ctx.stroke();ctx.setLineDash([]);}ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(x,y,16,0,Math.PI*2);ctx.fill();ctx.strokeStyle=c;ctx.lineWidth=3;ctx.stroke();ctx.fillStyle=c;ctx.font='bold 18px Arial';ctx.textAlign='center';ctx.fillText(iconFor(v),x,y+6);ctx.textAlign='left';ctx.fillStyle='#35483c';ctx.font='13px Arial';ctx.fillText(v.name,x+22,y+4);});
  ctx.fillStyle='#53685a';ctx.font='12px monospace';ctx.fillText('MAP LIBRARY OFFLINE · LOCAL SIMULATION GRID',18,24);
}
async function submitWaypoint(latitude, longitude) {
  if (!tasking) return;
  const vehicleId = $('map-vehicle').value;
  try {
    const mission = await api('/api/map/waypoint', { method: 'POST', body: JSON.stringify({ vehicle_id: vehicleId, latitude, longitude }) });
    current = mission; showPlan(mission); tasking = false;
    $('map-tasking').classList.remove('tasking-active'); $('map-tasking-status').textContent = 'TASKING OFF';
    $('map-tasking-status').classList.remove('tasking-ready');
    $('map-tasking-status').textContent = `PROPOSAL ${mission.id.toUpperCase()}`;
    await refresh();
  } catch (err) { $('map-tasking-status').textContent = 'INVALID WAYPOINT'; alert(err.message); }
}
function handleMapClick(e) {
  if (objectPlacement) { placeTestObjectAt(e.latlng.lat, e.latlng.lng); return; }
  if (coverageDrawing) { coveragePoints.push([e.latlng.lat,e.latlng.lng]); drawCoveragePreview(); return; }
  if (tasking) submitWaypoint(e.latlng.lat, e.latlng.lng);
}
function handleFallbackClick(e) {
  if ((!tasking && !coverageDrawing && !objectPlacement) || !mapConfig) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const px = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  const py = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
  const [latitude, longitude] = localToLatLng(px * 100, (1 - py) * 100);
  if (objectPlacement) { placeTestObjectAt(latitude, longitude); return; }
  if (coverageDrawing) { coveragePoints.push([latitude,longitude]); drawCoveragePreview(); return; }
  submitWaypoint(latitude, longitude);
}
function render(s) {
  lastState = s; updateMap(s.fleet, s.environment || {}); if(!map)drawFallback(s.fleet);
  const summary = s.summary || {}, activeMissions = (s.missions || []).filter(m => ['EXECUTING','RECOVERING','DEGRADED','PENDING_APPROVAL'].includes(m.status)).length;
  const ready = s.fleet.filter(v => !v.failed).length, pct = s.fleet.length ? Math.round(ready / s.fleet.length * 100) : 0;
  $('count').textContent = summary.vehicles_total ?? s.fleet.length; $('active').textContent = summary.vehicles_moving ?? 0;
  $('active-missions').textContent = activeMissions; $('readiness').innerHTML = `${pct}<small>%</small>`;
  $('readiness-label').textContent = pct === 100 ? 'All assets available' : `${s.fleet.length-ready} asset(s) unavailable`;
  $('missions').textContent = summary.missions_total ?? 0; $('low').textContent = (summary.low_battery || []).length;
  $('nav-fleet-count').textContent = s.fleet.length; $('fleet-pill').textContent = String(s.fleet.length).padStart(2,'0');
  $('map-asset-count').textContent = `${String(s.fleet.length).padStart(2,'0')} ASSETS TRACKED`;
  $('fleet-online').textContent = ready; $('fleet-unavailable').textContent = `${s.fleet.length-ready} unavailable`;
  $('fleet-health').textContent = `${pct}%`; $('fleet-health-bar').style.width = `${pct}%`;
  $('fleet').innerHTML = s.fleet.map(v => `<article class="vehicle-card"><div class="vehicle-top"><span class="vehicle-symbol ${v.kind==='fixed-wing'?'fixed':v.kind==='ground_robot'?'ground':'air'}">${iconFor(v)}</span><span class="vehicle-name"><b>${esc(v.name)}</b><small>${esc(v.kind.replace('_',' '))}</small></span><span class="vehicle-status ${statusClass(v)}">${esc(v.status.toUpperCase())}</span></div><div class="vehicle-meta"><span>${v.latitude.toFixed(5)}, ${v.longitude.toFixed(5)}</span><span>${Math.round(v.battery_pct)}% BATTERY</span></div><div class="battery-track"><i class="${v.battery_pct<20?'low':''}" style="width:${Math.max(0,Math.min(100,v.battery_pct))}%"></i></div></article>`).join('');
  $('failure-buttons').innerHTML = s.fleet.filter(v => !v.failed).map(v => `<button data-fail="${esc(v.id)}">⚠ &nbsp; Inject ${esc(v.name)} outage</button>`).join('') || '<small>No available assets.</small>';
  const selectedVehicle = $('map-vehicle').value;
  $('map-vehicle').innerHTML = s.fleet.filter(v => !v.failed && ['ready','holding'].includes(v.status)).map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');
  if ([...$('map-vehicle').options].some(o => o.value === selectedVehicle)) $('map-vehicle').value = selectedVehicle;
  if (current) { const m = s.missions.find(z => z.id === current.id); if (m) { current = m; showPlan(m); } }
}
function showPlan(m) {
  $('status').textContent = m.status.replaceAll('_',' '); $('proposal-id').textContent = `MISSION / ${m.id}`;
  $('proposal').textContent = `${m.instruction || 'Mission execution proposal'}\n\nPlanner: ${m.provider || 'offline'} · Coordinator: ${m.coordinator_provider || 'deterministic'}\n\n${(m.actions || []).map(a => `${a.vehicle_name}: ${a.action}${a.x != null ? ` → local (${a.x}, ${a.y})` : ''}`).join('\n')}\n\n${m.coverage_summary ? `\n\nCOVERAGE: ${m.coverage_summary.sector_count} sectors · ${m.coverage_summary.waypoint_count} waypoints · ${m.coverage_summary.lane_spacing_m} m spacing · reserve: ${m.coverage_summary.reserve_vehicle || 'none'}\n${m.coverage_summary.overlap_check}\n${m.coverage_summary.safety_check}` : ''}\n\n${(m.checks || []).map(c => '✓ ' + c).join('\n')}${m.map_target ? `\n\nWGS84 WAYPOINT: ${m.map_target.latitude.toFixed(6)}, ${m.map_target.longitude.toFixed(6)}` : ''}`;
  const operatorLinkAvailable = !!(swarmState?.config?.enabled && swarmState?.config?.coordinator_link_enabled);
  $('approve').disabled = m.status !== 'PENDING_APPROVAL' || !operatorLinkAvailable; $('reject').disabled = m.status !== 'PENDING_APPROVAL' || !operatorLinkAvailable;
  if (m.status === 'PENDING_APPROVAL' && !operatorLinkAvailable) $('proposal').textContent += '\n\nOPERATOR LINK UNAVAILABLE: restore communications before approving or rejecting this proposal.';
  const traces = m.agent_trace || [], names = ['Mission Planner','Fleet Coordinator','Safety & Policy','Execution Agent','Mission Monitor'], glyphs = ['✦','⟡','⬡','▷','◷'];
  $('agents').innerHTML = names.map((name,i) => { const trace = traces.find(t => t.toLowerCase().includes(name.toLowerCase().split(' ')[0])); const active = trace || ((i===3 && ['EXECUTING','RECOVERING','COMPLETED'].includes(m.status)) || (i===4 && ['EXECUTING','RECOVERING','COMPLETED','DEGRADED'].includes(m.status))); return `<div class="agent-row ${active?'running':''}"><span class="agent-glyph">${glyphs[i]}</span><span><b>${name}</b><small>${esc(trace || (active?'Active in workflow':i===2?'Deterministic policy checks':'Standing by'))}</small></span><i class="agent-state"></i></div>`; }).join('');
}
async function refresh() {
  try {
    const s = await api('/api/state'); render(s);
    $('events').textContent = (s.events || []).map(x => `${new Date(x.time).toLocaleTimeString()}  ${x.agent}: ${x.message}`).join('\n') || 'No events recorded yet.';
    await refreshSwarm();
    await refreshSensors();
  } catch (e) { console.error(e); }
}
$('plan').onclick = async () => { try { if (!$('cmd').value.trim()) throw Error('Enter a mission instruction first.'); current = await api('/api/plan',{method:'POST',body:JSON.stringify({instruction:$('cmd').value})}); showPlan(current); await refresh(); } catch(e) { alert(e.message); } };
$('approve').onclick = async () => { if (!current) return; try { current = await api(`/api/missions/${current.id}/approve`,{method:'POST'}); showPlan(current); await refresh(); } catch(e) { alert(e.message); } };
$('reject').onclick = async () => { if (!current) return; try { current = await api(`/api/missions/${current.id}/reject`,{method:'POST'}); showPlan(current); await refresh(); } catch(e) { alert(e.message); } };
$('reset').onclick = async () => { if (!confirm('Reset the simulation fleet, missions, virtual objects, blackbox and event history?')) return; try { current = null; setObjectPlacement(false); if(blackboxPlayTimer){clearInterval(blackboxPlayTimer);blackboxPlayTimer=null;} await api('/api/fleet/seed',{method:'POST'}); await refresh(); await refreshBlackbox(); } catch(e) { alert(e.message); } };
$('refresh-now').onclick = refresh;
$('failure-buttons').addEventListener('click', async e => { const button = e.target.closest('[data-fail]'); if (!button) return; try { const result = await api(`/api/vehicles/${button.dataset.fail}/fail`,{method:'POST'}); if(result.recovery_proposals?.length){current=result.recovery_proposals[0];showPlan(current);} await refresh(); if(!result.recovery_proposals?.length) alert('Failure detected. No compatible recovery asset is currently available.'); } catch(err) { alert(err.message); } });
document.querySelectorAll('[data-cmd]').forEach(b => b.onclick = () => $('cmd').value = b.dataset.cmd);
document.querySelectorAll('[data-layer]').forEach(b => b.onclick = () => { const layer=b.dataset.layer; layers[layer]=!layers[layer]; b.classList.toggle('active',layers[layer]); if(lastState) updateMap(lastState.fleet); if(sensorState) renderSensorMap(sensorState); });
$('map-tasking').onclick = () => {
  if (!map && !mapConfig) return;
  if(objectPlacement)setObjectPlacement(false);
  if (!$('map-vehicle').value) { alert('No available vehicle can accept a waypoint.'); return; }
  tasking = !tasking; $('map-tasking').classList.toggle('tasking-active',tasking);
  $('map-tasking-status').textContent = tasking ? 'CLICK MAP TO PLACE' : 'TASKING OFF';
  $('map-tasking-status').classList.toggle('tasking-ready',tasking);
  $('map').style.cursor = tasking ? 'crosshair' : ''; $('map-fallback').style.cursor = tasking ? 'crosshair' : '';
};
$('coverage-draw').onclick = () => {
  if(objectPlacement)setObjectPlacement(false);
  coverageDrawing=!coverageDrawing; tasking=false; $('map-tasking').classList.remove('tasking-active'); $('map-tasking-status').textContent='TASKING OFF';
  if(coverageDrawing){coveragePoints=[];if(coveragePreview&&map)map.removeLayer(coveragePreview);coveragePreview=null;coveragePointLayers.forEach(x=>map&&map.removeLayer(x));coveragePointLayers=[];}
  $('coverage-draw').textContent=coverageDrawing?'Cancel drawing':'＋ Draw area';
  $('map').style.cursor=coverageDrawing?'crosshair':''; $('map-fallback').style.cursor=coverageDrawing?'crosshair':''; drawCoveragePreview();
};
$('coverage-clear').onclick=()=>{coveragePoints=[];coverageDrawing=false;$('coverage-draw').textContent='＋ Draw area';if(coveragePreview&&map)map.removeLayer(coveragePreview);coveragePreview=null;coveragePointLayers.forEach(x=>map&&map.removeLayer(x));coveragePointLayers=[];drawCoveragePreview();};
$('coverage-finish').onclick=async()=>{
  if(coveragePoints.length<3){alert('Add at least three boundary points.');return;}
  try{
    const polygon=coveragePoints.map(([latitude,longitude])=>({latitude,longitude}));
    const mission=await api('/api/missions/coverage/plan',{method:'POST',body:JSON.stringify({polygon,lane_spacing_m:Number($('coverage-spacing').value)})});
    current=mission;coverageDrawing=false;$('coverage-draw').textContent='＋ Draw area';$('map').style.cursor='';$('map-fallback').style.cursor='';
    if(coveragePreview&&map)map.removeLayer(coveragePreview);coveragePreview=null;coveragePointLayers.forEach(x=>map&&map.removeLayer(x));coveragePointLayers=[];coveragePoints=[];
    $('coverage-status').textContent=`Proposal ${mission.id.toUpperCase()} · ${(mission.coverage_summary||{}).sector_count||0} sectors · ${(mission.coverage_summary||{}).waypoint_count||0} waypoints`;
    showPlan(mission);await refresh();
  }catch(e){$('coverage-status').textContent='Coverage proposal rejected';alert(e.message);}
};
$('map-fit').onclick = () => { if(map && mapConfig) map.fitBounds(L.latLngBounds(mapConfig.bounds).pad(.08)); else { drawFallback(lastState?.fleet || []); $('map-tasking-status').textContent = 'FULL THEATRE IN VIEW'; } };



function setObjectPlacement(enabled, objectId = null) {
  objectPlacement = !!enabled;
  movingObjectId = objectPlacement ? objectId : null;
  tasking = false;
  $('map-tasking').classList.remove('tasking-active');
  $('map-tasking-status').textContent = objectPlacement ? (objectId ? 'CLICK MAP TO MOVE OBJECT' : 'CLICK MAP TO PLACE OBJECT') : 'TASKING OFF';
  $('object-place-mode').classList.toggle('tasking-active', objectPlacement);
  $('sensor-place-object').classList.toggle('tasking-active', objectPlacement);
  $('object-place-mode').textContent = objectPlacement ? 'Cancel object placement' : '＋ Place test object';
  $('sensor-place-object').textContent = objectPlacement ? 'Cancel placement' : 'Place on map';
  $('map').style.cursor = objectPlacement ? 'crosshair' : '';
  $('map-fallback').style.cursor = objectPlacement ? 'crosshair' : '';
  $('sensor-placement-note').textContent = objectPlacement
    ? (objectId ? 'Click a new map location to move the selected object.' : 'Click inside the operating geofence to place this virtual object.')
    : 'Select Place on map, then click inside the operating boundary. Choose Move beside an existing object to reposition it.';
  if (objectPlacement) setTimeout(() => document.querySelector('.map-canvas-wrap')?.scrollIntoView({behavior:'smooth', block:'center'}), 60);
}

async function placeTestObjectAt(latitude, longitude) {
  if (!objectPlacement) return;
  const point = wgs84ToLocalFallback(latitude, longitude);
  try {
    let result;
    if (movingObjectId) {
      result = await api(`/api/sensors/objects/${movingObjectId}`, {method:'PUT', body:JSON.stringify({x:point.x, y:point.y})});
      $('sensor-placement-note').textContent = `Moved ${result.label} to local (${result.x.toFixed(1)}, ${result.y.toFixed(1)}).`;
    } else {
      result = await api('/api/sensors/objects', {method:'POST', body:JSON.stringify({
        x:point.x, y:point.y, label:$('test-object-label').value.trim(),
        category:$('test-object-category').value, difficulty:$('test-object-difficulty').value,
        visible:$('test-object-visible').checked,
      })});
      $('sensor-placement-note').textContent = `Placed ${result.label} at local (${result.x.toFixed(1)}, ${result.y.toFixed(1)}). Run a scan or wait for the next simulation tick.`;
    }
    setObjectPlacement(false);
    await refreshSensors();
  } catch (e) {
    $('sensor-placement-note').textContent = e.message;
  }
}

function renderSensorMap(data) {
  if (!map || !window.L || !data) {
    if (lastState) drawFallback(lastState.fleet);
    return;
  }
  const upsertCircle = (collection, key, ll, radius, style, enabled, tip) => {
    let layer = collection.get(key);
    if (!enabled) {
      if (layer) { map.removeLayer(layer); collection.delete(key); }
      return;
    }
    if (!layer) {
      layer = L.circle(ll, {radius, ...style, interactive:false}).addTo(map);
      collection.set(key, layer);
    } else {
      layer.setLatLng(ll); layer.setRadius(radius); layer.setStyle(style);
      if (!map.hasLayer(layer)) layer.addTo(map);
    }
    if (tip && !layer.getTooltip()) layer.bindTooltip(tip, {sticky:true, className:'sensor-tooltip'});
  };
  const liveIds = new Set();
  (data.vehicles || []).forEach(v => {
    const ll = localToLatLng(v.x, v.y); liveIds.add(v.vehicle_id);
    const color = palette[(lastState?.fleet || []).find(a=>a.id===v.vehicle_id)?.kind] || '#55906e';
    upsertCircle(sensorMapLayers.footprints, v.vehicle_id, ll, v.sensor_range_m,
      {color, weight:1.5, opacity:.75, fillColor:color, fillOpacity:.075},
      layers.sensors && v.sensor_enabled && !v.failed, `${esc(v.vehicle_name)} · simulated sensor ${Math.round(v.sensor_range_m)} m`);
    upsertCircle(sensorMapLayers.comms, v.vehicle_id, ll, v.comm_range_m,
      {color:'#7d91ab', weight:1.2, opacity:.8, dashArray:'5 6', fillColor:'#8ea2ba', fillOpacity:.025},
      layers.comms && !v.failed, `${esc(v.vehicle_name)} · illustrative comm range ${Math.round(v.comm_range_m)} m`);
  });
  for (const collection of [sensorMapLayers.footprints, sensorMapLayers.comms]) {
    for (const [key, layer] of collection) if (!liveIds.has(key)) { map.removeLayer(layer); collection.delete(key); }
  }

  const activeObjects = new Set();
  (data.objects || []).forEach(obj => {
    activeObjects.add(obj.object_id);
    let layer = sensorMapLayers.objects.get(obj.object_id);
    if (!layers.objects) { if (layer) { map.removeLayer(layer); sensorMapLayers.objects.delete(obj.object_id); } return; }
    const ll = localToLatLng(obj.x, obj.y);
    const icon = L.divIcon({className:'test-object-icon-wrap', html:`<div class="test-object-marker ${obj.visible?'':'hidden-object'}">◇</div>`, iconSize:[27,27], iconAnchor:[13,13]});
    const status = obj.information_status || 'UNOBSERVED';
    const popup = `<div class="map-popup"><b>${esc(obj.label)}</b><span>${esc(obj.category)} · ${esc(obj.difficulty)} · ${obj.visible?'visible':'hidden'}</span><span>Local (${obj.x.toFixed(1)}, ${obj.y.toFixed(1)})</span><span>${obj.observation_count} observation(s) · ${esc(status)}</span></div>`;
    if (!layer) { layer = L.marker(ll,{icon,title:obj.label}).addTo(map); sensorMapLayers.objects.set(obj.object_id,layer); }
    layer.setLatLng(ll).setIcon(icon).bindPopup(popup);
  });
  for (const [key, layer] of sensorMapLayers.objects) if (!activeObjects.has(key)) { map.removeLayer(layer); sensorMapLayers.objects.delete(key); }

  const obsIds = new Set();
  if (layers.observations) (data.observations || []).slice(0,120).forEach(obs => {
    obsIds.add(obs.observation_id);
    const ll = localToLatLng(obs.x, obs.y), color = obs.shared_status === 'SHARED' ? '#438c6b' : '#ca8842';
    let layer = sensorMapLayers.observations.get(obs.observation_id);
    const popup = `<div class="map-popup"><b>${esc(obs.label)}</b><span>Observed by ${esc(obs.source_vehicle_name)}</span><span>Confidence score ${Math.round(obs.confidence*100)}%</span><span>${esc(obs.shared_status)} · ${esc(obs.modality)}</span></div>`;
    if (!layer) { layer = L.circleMarker(ll,{radius:6,color:'#fff',weight:2,fillColor:color,fillOpacity:.95}).addTo(map); sensorMapLayers.observations.set(obs.observation_id,layer); }
    layer.setLatLng(ll).setStyle({fillColor:color}).bindPopup(popup);
  });
  for (const [key, layer] of sensorMapLayers.observations) if (!obsIds.has(key)) { map.removeLayer(layer); sensorMapLayers.observations.delete(key); }

  if (blackboxReplaySample) showReplayOnMap(false);
}

function renderSensorState(data) {
  sensorState = data;
  const summary = data.summary || {};
  $('sensor-object-count').textContent = summary.active_objects ?? 0;
  $('sensor-observation-count').textContent = summary.observations ?? 0;
  $('sensor-corroborated-count').textContent = summary.corroborated_objects ?? 0;
  $('sensor-overlap-count').textContent = (data.overlap_pairs || []).length;
  $('sensor-object-list').innerHTML = (data.objects || []).map(obj => `
    <article class="sensor-object-row" data-object-row="${esc(obj.object_id)}">
      <div class="sensor-object-row-top"><b>${esc(obj.label)}</b><span class="sensor-status-pill ${obj.information_status==='CORROBORATED'?'':'warn'}">${esc(obj.information_status)}</span></div>
      <small>${esc(obj.category)} · ${esc(obj.difficulty)} · local (${obj.x.toFixed(1)}, ${obj.y.toFixed(1)}) · ${obj.visible?'visible':'hidden'}<br>${obj.observation_count} observation(s) from ${(obj.observed_by||[]).map(esc).join(', ') || 'no vehicles'}</small>
      <div class="sensor-object-actions"><button data-object-move="${esc(obj.object_id)}">Move</button><button data-object-toggle="${esc(obj.object_id)}" data-visible="${obj.visible?'1':'0'}">${obj.visible?'Hide':'Show'}</button><button data-object-delete="${esc(obj.object_id)}">Remove</button></div>
    </article>`).join('') || '<span class="muted-text">No virtual objects placed. Use Place on map to add one.</span>';
  $('sensor-observation-list').innerHTML = (data.observations || []).slice(0,30).map(obs => `
    <article class="sensor-observation-row"><div class="sensor-observation-row-top"><b>${esc(obs.label)}</b><span class="sensor-status-pill ${obs.shared_status==='SHARED'?'':'warn'}">${esc(obs.shared_status)}</span></div>
      <small>${esc(obs.source_vehicle_name)} · ${(obs.confidence*100).toFixed(0)}% score · ${Math.round(obs.distance_m)} m from object<br>${new Date(obs.timestamp).toLocaleTimeString()} · ${esc(obs.modality)}</small></article>`).join('') || '<span class="muted-text">No observations yet. Place an object inside a sensor footprint.</span>';
  if (!document.activeElement?.closest('#sensor-vehicle-settings')) {
    $('sensor-vehicle-settings').innerHTML = (data.vehicles || []).map(v => `
      <div class="sensor-vehicle-row" data-sensor-vehicle="${esc(v.vehicle_id)}">
        <div class="sensor-vehicle-row-head"><b>${esc(v.vehicle_name)}</b><small>${esc(v.status)}${v.failed?' · failed':''}</small></div>
        <label class="control-row"><span>Sensor enabled</span><input type="checkbox" data-sensor-setting="sensor_enabled" data-vehicle="${esc(v.vehicle_id)}" ${v.sensor_enabled?'checked':''}></label>
        <label class="control-row"><span>Sensor radius</span><span class="sensor-value"><input aria-label="${esc(v.vehicle_name)} sensor range" type="range" min="50" max="1000" step="10" value="${v.sensor_range_m}" data-sensor-setting="sensor_range_m" data-vehicle="${esc(v.vehicle_id)}"><output>${Math.round(v.sensor_range_m)} m</output></span></label>
        <label class="control-row"><span>Comm range</span><span class="sensor-value"><input aria-label="${esc(v.vehicle_name)} communication range" type="range" min="100" max="2000" step="25" value="${v.comm_range_m}" data-sensor-setting="comm_range_m" data-vehicle="${esc(v.vehicle_id)}"><output>${Math.round(v.comm_range_m)} m</output></span></label>
      </div>`).join('');
  }
  renderSensorMap(data);
}
async function refreshSensors() {
  try { renderSensorState(await api('/api/sensors/state')); } catch (e) { console.error('Sensor state refresh failed', e); }
}

function drawTelemetryChart(canvasId, samples, field, stroke, maxValue, unit) {
  const canvas = $(canvasId); if (!canvas) return;
  const ctx = canvas.getContext('2d'), w=canvas.width, h=canvas.height, pad=26;
  ctx.clearRect(0,0,w,h); ctx.fillStyle='#fbfcfa'; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle='#e9eee8'; ctx.lineWidth=1;
  for(let i=0;i<4;i++){const y=pad+i*(h-pad*2)/3;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke();}
  ctx.fillStyle='#9aa49d';ctx.font='10px Arial';ctx.fillText(`${maxValue}${unit}`,3,pad+3);ctx.fillText('0',12,h-pad+3);
  if (!samples.length) { ctx.fillText('Waiting for telemetry samples…',w/2-80,h/2); return; }
  const values=samples.map(s=>Number(s[field]||0)), peak=Math.max(maxValue,...values), min=0;
  const x=i=>pad+(samples.length<=1?0:i/(samples.length-1))*(w-pad*2);
  const y=v=>h-pad-(v-min)/(peak-min||1)*(h-pad*2);
  ctx.beginPath();values.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v)));
  ctx.strokeStyle=stroke;ctx.lineWidth=2.5;ctx.lineJoin='round';ctx.stroke();
  ctx.lineTo(x(values.length-1),h-pad);ctx.lineTo(x(0),h-pad);ctx.closePath();ctx.fillStyle=stroke+'18';ctx.fill();
  ctx.fillStyle='#829087';ctx.font='9px Arial';ctx.fillText(`${values[values.length-1].toFixed(1)} ${unit}`,w-pad-65,13);
}
function selectedBlackboxSample() {
  if (!blackboxData?.samples?.length) return null;
  const idx = Math.max(0, Math.min(blackboxData.samples.length-1, Number($('blackbox-replay-slider').value)||0));
  return blackboxData.samples[idx];
}
function showReplayOnMap(shouldCenter = true) {
  const sample=selectedBlackboxSample(); if(!sample) return;
  blackboxReplaySample=sample;
  const ll=localToLatLng(sample.x,sample.y);
  if(map && window.L){
    const icon=L.divIcon({className:'replay-icon-wrap',html:'<div class="replay-dot"></div>',iconSize:[17,17],iconAnchor:[8,8]});
    if(!blackboxReplayMarker) blackboxReplayMarker=L.marker(ll,{icon,zIndexOffset:1200}).addTo(map);
    blackboxReplayMarker.setLatLng(ll).setIcon(icon).bindTooltip(`REPLAY · ${esc(sample.vehicle_name)} · ${new Date(sample.timestamp).toLocaleTimeString()}`);
    if(shouldCenter) map.panTo(ll);
  } else if(lastState) drawFallback(lastState.fleet);
  $('blackbox-replay-label').textContent=`${sample.vehicle_name} · local (${sample.x.toFixed(2)}, ${sample.y.toFixed(2)}) · ${sample.status}`;
  $('blackbox-replay-time').textContent=new Date(sample.timestamp).toLocaleTimeString();
  $('blackbox-show-map').disabled=false;
}
function renderBlackbox(data) {
  blackboxData=data;
  const samples=data.samples||[], last=samples[samples.length-1], peak=Math.max(0,...samples.map(x=>x.speed_mps||0));
  let distance=0;for(let i=1;i<samples.length;i++)distance+=Math.hypot(samples[i].x-samples[i-1].x,samples[i].y-samples[i-1].y)*(mapConfig?.width_m||2000)/100;
  $('blackbox-samples').textContent=data.sample_count??samples.length;
  $('blackbox-battery').textContent=last?`${last.battery_pct.toFixed(1)}%`:'—';
  $('blackbox-peak-speed').textContent=`${peak.toFixed(2)} m/s`;
  $('blackbox-distance').textContent=`${distance.toFixed(0)} m`;
  $('blackbox-status').textContent=last?String(last.status).toUpperCase():'—';
  drawTelemetryChart('blackbox-speed-chart',samples,'speed_mps','#4b9170',6,' m/s');
  drawTelemetryChart('blackbox-battery-chart',samples,'battery_pct','#c08b43',100,'%');
  const slider=$('blackbox-replay-slider');slider.max=Math.max(0,samples.length-1);slider.disabled=!samples.length;
  if(!blackboxPlayTimer && samples.length) slider.value=samples.length-1;
  $('blackbox-play').disabled=samples.length<2;$('blackbox-show-map').disabled=!samples.length;
  $('blackbox-event-list').innerHTML=(data.events||[]).slice(0,18).map(e=>`<article class="blackbox-event"><b>${esc(e.event_type)}</b><small>${esc(e.vehicle_id||'SYSTEM')} · ${new Date(e.timestamp).toLocaleTimeString()}</small><p>${esc(JSON.stringify(e.payload||{}).slice(0,210))}</p></article>`).join('')||'<span class="muted-text">No recorded events.</span>';
  if(samples.length && !blackboxPlayTimer) showReplayOnMap(false);
  else if(!samples.length){blackboxReplaySample=null;if(blackboxReplayMarker&&map){map.removeLayer(blackboxReplayMarker);blackboxReplayMarker=null;}}
}
async function refreshBlackbox() {
  if (!lastState?.fleet?.length) return;
  const select=$('blackbox-vehicle'), selected=select.value;
  const fleet=lastState.fleet;
  select.innerHTML=fleet.map(v=>`<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');
  if(fleet.some(v=>v.id===selected))select.value=selected;
  else select.value=fleet[0].id;
  const data=await api(`/api/blackbox?vehicle_id=${encodeURIComponent(select.value)}&limit=180`);
  renderBlackbox(data);
}

function renderSwarm(data) {
  swarmState = data;
  const c = data.connectivity || {}, cfg = data.config || {}, radios = data.radios || {};
  $('swarm-status').innerHTML = `<i></i> ${esc(c.network_status || 'UNKNOWN')}`;
  $('swarm-status').classList.toggle('paused', !cfg.enabled);
  $('swarm-network-value').textContent = c.network_status || '—';
  $('swarm-radios-value').textContent = `${c.radios_online ?? 0}/${c.vehicles_total ?? 0}`;
  $('swarm-mesh-value').textContent = c.peer_mesh_available ? 'AVAILABLE' : 'OFF';
  $('swarm-detections-value').textContent = (data.knowledge?.detections || []).length;
  $('swarm-messages-value').textContent = (data.messages || []).length;
  if (!swarmConfigDirty) {
    $('swarm-enabled').checked = !!cfg.enabled;
    $('swarm-mode').value = cfg.coordination_mode || 'hybrid';
    $('swarm-peer-mesh').checked = !!cfg.peer_mesh_enabled;
    $('swarm-central-link').checked = !!cfg.coordinator_link_enabled;
    $('swarm-latency').value = Number(cfg.network_latency_ticks || 0);
    $('swarm-packet-loss').value = Number(cfg.packet_loss_pct || 0);
  }

  const fleet = lastState?.fleet || [];
  $('swarm-radios').innerHTML = fleet.map(v => `<label class="radio-vehicle-row"><span><b>${esc(v.name)}</b><small>${esc(v.kind.replace('_',' '))} · ${esc(v.status)}</small></span><input type="checkbox" data-radio="${esc(v.id)}" ${radios[v.id] ? 'checked' : ''} aria-label="Enable ${esc(v.name)} radio"></label>`).join('') || '<span class="muted-text">No registered vehicles.</span>';
  const optionHTML = fleet.map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');
  for (const id of ['peer-test-sender','peer-test-recipient','detection-source']) {
    const select = $(id), old = select.value;
    select.innerHTML = optionHTML;
    if ([...select.options].some(o => o.value === old)) select.value = old;
    else if (id === 'peer-test-recipient' && select.options.length > 1) select.selectedIndex = 1;
  }
  const recipient = $('swarm-recipient'), oldRecipient = recipient.value;
  recipient.innerHTML = '<option value="all">All connected vehicles</option>' + optionHTML;
  if ([...recipient.options].some(o => o.value === oldRecipient)) recipient.value = oldRecipient;

  const vehicles = data.knowledge?.vehicles || {};
  $('swarm-shared-picture').innerHTML = fleet.map(v => {
    const k = vehicles[v.id] || {};
    const seen = k.last_seen ? new Date(k.last_seen).toLocaleTimeString() : 'not yet heard';
    return `<div class="shared-vehicle-row"><span class="shared-led ${radios[v.id] && cfg.enabled ? 'online' : ''}"></span><span><b>${esc(v.name)}</b><small>${esc(k.status || v.status)} · ${Math.round(k.battery_pct ?? v.battery_pct)}% battery · ${radios[v.id] ? 'radio on' : 'radio off'}</small></span><time>${esc(seen)}</time></div>`;
  }).join('');
  $('swarm-message-feed').innerHTML = (data.messages || []).slice(0,60).map(m => {
    const when = new Date(m.timestamp).toLocaleTimeString();
    const to = (m.delivered_to || []).join(', ') || ((m.queued_to || []).length ? `queued: ${m.queued_to.join(', ')}` : 'no recipient');
    const payload = JSON.stringify(m.payload || {});
    return `<article class="swarm-message"><div><b>${esc(m.message_type)}</b><span class="message-state ${String(m.status).startsWith('DELIVERED') ? 'delivered' : String(m.status).startsWith('PARTIAL') ? 'partial' : String(m.status).startsWith('QUEUED') ? 'partial' : 'blocked'}">${esc(m.status)}</span></div><small>${esc(m.sender)} → ${esc(to)} · ${esc(when)}</small><p>${esc(payload.length > 230 ? payload.slice(0,227)+'…' : payload)}</p></article>`;
  }).join('') || '<span class="muted-text">No swarm messages yet. Request status or run a peer link test.</span>';
}
async function refreshSwarm() {
  try { renderSwarm(await api('/api/swarm/state')); } catch (e) { console.error('Swarm refresh failed', e); }
}
async function applySwarmConfig() {
  const config = {
    enabled: $('swarm-enabled').checked,
    coordination_mode: $('swarm-mode').value,
    peer_mesh_enabled: $('swarm-peer-mesh').checked,
    coordinator_link_enabled: $('swarm-central-link').checked,
    network_latency_ticks: Number($('swarm-latency').value),
    packet_loss_pct: Number($('swarm-packet-loss').value),
  };
  try {
    const result = await api('/api/swarm/config', {method:'PUT', body:JSON.stringify(config)});
    swarmConfigDirty = false;
    renderSwarm(result);
    $('swarm-config-note').textContent = 'Network policy applied and persisted.';
    await refresh();
  } catch (e) { alert(e.message); }
}
for (const id of ['swarm-enabled','swarm-mode','swarm-peer-mesh','swarm-central-link','swarm-latency','swarm-packet-loss']) $(id).addEventListener('change', () => { swarmConfigDirty = true; });
$('swarm-save-config').onclick = applySwarmConfig;
$('swarm-radios').addEventListener('change', async e => {
  const input = e.target.closest('[data-radio]'); if (!input) return;
  try { renderSwarm(await api(`/api/swarm/vehicles/${input.dataset.radio}/radio`, {method:'PUT',body:JSON.stringify({enabled:input.checked})})); await refresh(); }
  catch (err) { alert(err.message); input.checked = !input.checked; }
});
$('swarm-broadcast').onclick = async () => {
  const message = $('swarm-broadcast-text').value.trim();
  if (message.length < 2) { alert('Enter a broadcast message.'); return; }
  const selected = $('swarm-recipient').value;
  try {
    const result = await api('/api/swarm/broadcast', {method:'POST',body:JSON.stringify({message,recipients:selected==='all'?null:[selected]})});
    $('swarm-config-note').textContent = `Broadcast ${result.status.toLowerCase()}; delivered to ${(result.delivered_to||[]).length} vehicle(s).`;
    if (result.status === 'DELIVERED' || result.status === 'PARTIAL') $('swarm-broadcast-text').value = '';
    await refresh();
  } catch (e) { alert(e.message); }
};
$('swarm-status-request').onclick = async () => {
  try { const result = await api('/api/swarm/status-request',{method:'POST'}); $('swarm-config-note').textContent = `Received ${result.reports.length} status report(s).`; await refresh(); }
  catch(e) { alert(e.message); }
};
$('swarm-peer-test').onclick = async () => {
  try {
    const result = await api('/api/swarm/peer-test',{method:'POST',body:JSON.stringify({sender_vehicle_id:$('peer-test-sender').value,recipient_vehicle_id:$('peer-test-recipient').value,message:'Operator requested peer-to-peer connectivity test'})});
    $('swarm-config-note').textContent = `Peer test result: ${result.status} · delivered to ${(result.delivered_to||[]).join(', ') || 'nobody'}.`;
    await refresh();
  } catch(e) { alert(e.message); }
};
$('swarm-detection-submit').onclick = async () => {
  const payload = {source_vehicle_id:$('detection-source').value, x:Number($('detection-x').value), y:Number($('detection-y').value), label:$('detection-label').value.trim(), confidence:Number($('detection-confidence').value)};
  try {
    const result = await api('/api/swarm/detections',{method:'POST',body:JSON.stringify(payload)});
    const proposal = result.proposal;
    $('swarm-detection-result').textContent = proposal ? `Detection shared. ${proposal.actions[0].vehicle_name} offered to investigate. Proposal ${proposal.id} is awaiting operator approval.${proposal.coordination_mode === 'peer-negotiated' ? ' Peer negotiation worked without the coordinator link; restore that link before approval.' : ''}` : 'Detection shared, but no eligible vehicle could offer to investigate.';
    if (proposal) { current = proposal; showPlan(proposal); }
    await refresh();
  } catch(e) { alert(e.message); }
};
$('swarm-conflict-scan').onclick = async () => {
  try { const result = await api('/api/swarm/conflicts/check',{method:'POST'}); $('swarm-config-note').textContent = `${result.count} potential destination conflict(s) detected. ${result.note}`; await refresh(); }
  catch(e) { alert(e.message); }
};


$('object-place-mode').onclick = () => setObjectPlacement(!objectPlacement);
$('sensor-place-object').onclick = () => setObjectPlacement(!objectPlacement);
$('sensor-object-list').addEventListener('click', async e => {
  const move=e.target.closest('[data-object-move]'), toggle=e.target.closest('[data-object-toggle]'), remove=e.target.closest('[data-object-delete]');
  try {
    if(move){setObjectPlacement(true,move.dataset.objectMove);return;}
    if(toggle){const visible=toggle.dataset.visible!=='1';await api(`/api/sensors/objects/${toggle.dataset.objectToggle}`,{method:'PUT',body:JSON.stringify({visible})});await refreshSensors();return;}
    if(remove){await api(`/api/sensors/objects/${remove.dataset.objectDelete}`,{method:'DELETE'});await refreshSensors();return;}
  } catch(err){$('sensor-placement-note').textContent=err.message;}
});
$('sensor-scan-now').onclick = async () => {
  try {
    const result=await api('/api/sensors/scan',{method:'POST'});
    $('sensor-placement-note').textContent=`Scan complete: ${result.count} observation(s), ${result.automated_proposals?.length || 0} automatic inspection proposal(s). ${result.automated_proposals?.length ? 'Review the proposal in Mission Control; approval is still required.' : 'No object met the automation policy.'}`;
    if (result.automated_proposals?.length) { current=result.automated_proposals[0].proposal; showPlan(current); }
    await refresh(); await refreshSensors(); await refreshSwarm(); await refreshBlackbox();
  } catch(e){$('sensor-placement-note').textContent=e.message;}
};
$('sensor-vehicle-settings').addEventListener('input', e => {
  const input=e.target.closest('input[type=range][data-sensor-setting]');if(!input)return;
  const output=input.parentElement.querySelector('output');if(output)output.textContent=`${Math.round(Number(input.value))} m`;
});
$('sensor-vehicle-settings').addEventListener('change', async e => {
  const input=e.target.closest('[data-sensor-setting]');if(!input)return;
  const id=input.dataset.vehicle, key=input.dataset.sensorSetting;
  const value=input.type==='checkbox'?input.checked:Number(input.value);
  try { await api(`/api/sensors/vehicles/${id}`,{method:'PUT',body:JSON.stringify({[key]:value})});await refreshSensors();await refreshBlackbox(); }
  catch(err){alert(err.message);await refreshSensors();}
});
$('blackbox-vehicle').addEventListener('change',()=>refreshBlackbox().catch(e=>alert(e.message)));
$('blackbox-refresh').onclick=()=>refreshBlackbox().catch(e=>alert(e.message));
$('blackbox-replay-slider').addEventListener('input',()=>showReplayOnMap(false));
$('blackbox-show-map').onclick=()=>showReplayOnMap(true);
$('blackbox-play').onclick=()=>{
  if(blackboxPlayTimer){clearInterval(blackboxPlayTimer);blackboxPlayTimer=null;$('blackbox-play').textContent='▶ Play replay';return;}
  if(!blackboxData?.samples?.length)return;
  $('blackbox-play').textContent='Ⅱ Pause replay';
  let idx=Number($('blackbox-replay-slider').value)||0;
  blackboxPlayTimer=setInterval(()=>{
    idx+=1;if(idx>=blackboxData.samples.length){clearInterval(blackboxPlayTimer);blackboxPlayTimer=null;$('blackbox-play').textContent='▶ Play replay';idx=blackboxData.samples.length-1;}
    $('blackbox-replay-slider').value=idx;showReplayOnMap(false);
  },350);
};

async function boot() {
  try {
    mapConfig = await api('/api/map/config');
    $('theatre-name').textContent = mapConfig.origin.label;
    $('map-projection-note').textContent = `${mapConfig.width_m.toLocaleString()} M DEMO THEATRE · APPROXIMATE LOCAL PROJECTION`;
    const home = localToLatLng(10,10); $('home-coordinate').textContent = `${home[0].toFixed(5)}, ${home[1].toFixed(5)}`;
    initMap();
  } catch (e) { console.error('Map configuration unavailable',e); }
  await refresh();
  await refreshBlackbox();
  setInterval(async()=>{try{await api('/api/simulation/tick',{method:'POST'});await refresh();}catch(e){}},1000);
  setInterval(()=>{refreshBlackbox().catch(e=>console.error('Blackbox refresh failed',e));},4000);
  setInterval(()=>$('clock').textContent=new Date().toISOString().slice(11,19)+' UTC',1000);
}
boot();
