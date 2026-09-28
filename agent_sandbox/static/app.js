const imagesElement = document.querySelector('#images');
const imagesEmpty = document.querySelector('#images-empty');
const imageCount = document.querySelector('#image-count');
const template = document.querySelector('#image-template');
const createForm = document.querySelector('#create-form');
const imageIdInput = document.querySelector('#image-id');
const formError = document.querySelector('#form-error');
const submitCreate = document.querySelector('#submit-create');
const createView = document.querySelector('#create-view');
const imageView = document.querySelector('#image-view');
const imageNotice = document.querySelector('#image-notice');
const frame = document.querySelector('#opencode-frame');
const pageTitle = document.querySelector('#page-title');
const createNav = document.querySelector('#create-nav');
const toggleButton = document.querySelector('#sidebar-toggle');
function createSessionId() {
  const bytes = new Uint8Array(24);
  if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
}
const sessionId = sessionStorage.getItem('agent-sandbox-session') || createSessionId();
sessionStorage.setItem('agent-sandbox-session', sessionId);
let selectedId = null;
let activeId = null;
let images = [];

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || '操作に失敗しました。');
  return body;
}

function sessionBody() { return JSON.stringify({session_id: sessionId}); }
function imageEndpoint(id, action) { return `/manager/api/images/${encodeURIComponent(id)}/${action}`; }
function statusLabel(image) {
  if (image.status === 'connected') return '接続中';
  return image.status === 'running' ? '起動中' : '停止中';
}
function setCurrentPage(title, isCreate = false) {
  pageTitle.textContent = title;
  createNav.classList.toggle('active', isCreate);
  if (isCreate) createNav.setAttribute('aria-current', 'page');
  else createNav.removeAttribute('aria-current');
  for (const button of imagesElement.querySelectorAll('.image-item')) {
    if (button.dataset.imageId === selectedId && !isCreate) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
}
function setActiveImage(id) {
  activeId = id;
  if (id) sessionStorage.setItem('agent-sandbox-active-image', id);
  else sessionStorage.removeItem('agent-sandbox-active-image');
}
function clearImagePanel() {
  frame.src = 'about:blank';
  frame.hidden = true;
  imageNotice.hidden = true;
  imageNotice.replaceChildren();
}
function showCreate() {
  clearImagePanel();
  imageView.hidden = true;
  createView.hidden = false;
  formError.hidden = true;
  formError.textContent = '';
  setCurrentPage('新規作成', true);
}
function addAction(container, text, kind, handler, disabled = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'notice-action';
  button.dataset.kind = kind;
  button.textContent = text;
  if (kind === 'start' || kind === 'connect') button.classList.add('primary');
  if (kind === 'stop') button.classList.add('danger');
  button.disabled = disabled;
  button.addEventListener('click', handler);
  container.append(button);
  return button;
}
function showNotice(image, message, actions = []) {
  clearImagePanel();
  createView.hidden = true;
  imageView.hidden = false;
  imageNotice.hidden = false;
  const status = document.createElement('span');
  status.className = 'image-status';
  const dot = document.createElement('span');
  dot.className = 'image-status-dot';
  dot.dataset.status = image.status;
  const statusText = document.createElement('span');
  statusText.textContent = statusLabel(image);
  status.append(dot, statusText);
  const title = document.createElement('strong');
  title.textContent = image.id;
  const description = document.createElement('span');
  description.className = 'image-notice-message';
  description.textContent = message;
  imageNotice.append(status, title, description);
  if (actions.length) {
    const actionRow = document.createElement('div');
    actionRow.className = 'notice-actions';
    imageNotice.append(actionRow);
    actions.forEach((action) => addAction(actionRow, action.label, action.kind, action.onClick, action.disabled));
  }
  setCurrentPage(image.id);
}
function showImage(image) {
  selectedId = image.id;
  createView.hidden = true;
  imageView.hidden = false;
  if (image.status === 'connected' && image.connected_by_me && image.url) {
    imageNotice.hidden = true;
    imageNotice.replaceChildren();
    frame.src = image.url;
    frame.hidden = false;
    setCurrentPage(image.id);
    return;
  }
  if (image.status === 'connected') {
    showNotice(image, '別のセッションが接続中です。このイメージは現在使用できません。');
  } else if (image.status === 'running') {
    showNotice(image, '起動中です。接続するとメイン画面に作業環境を表示します。', [
      {label: '接続', kind: 'connect', onClick: () => connectImage(image)},
      {label: '停止', kind: 'stop', onClick: () => runImageAction(image, 'stop')},
    ]);
  } else {
    showNotice(image, '停止中です。起動してから接続できます。', [
      {label: '起動', kind: 'start', onClick: () => runImageAction(image, 'start')},
    ]);
  }
}
async function disconnectActive() {
  const id = activeId;
  if (!id) return;
  setActiveImage(null);
  clearImagePanel();
  try {
    await request(imageEndpoint(id, 'disconnect'), {method: 'POST', body: sessionBody()});
  } catch (error) {
    console.warn('切断要求を完了できませんでした。', error.message);
  }
}
async function connectImage(image) {
  if (activeId && activeId !== image.id) await disconnectActive();
  clearImagePanel();
  const connecting = {...image, status: 'running'};
  showNotice(connecting, '接続しています…');
  try {
    const connected = await request(imageEndpoint(image.id, 'connect'), {method: 'POST', body: sessionBody()});
    setActiveImage(image.id);
    showImage(connected);
  } catch (error) {
    setActiveImage(null);
    const latest = (await refresh().catch(() => images)).find((item) => item.id === image.id) || image;
    showNotice({...latest, status: latest.status === 'connected' ? 'connected' : 'running'}, error.message);
  }
}
async function selectImage(image) {
  selectedId = image.id;
  if (activeId && activeId !== image.id) await disconnectActive();
  const latest = (await refresh().catch(() => images)).find((item) => item.id === image.id) || image;
  if (latest.status === 'stopped') {
    showImage(latest);
  } else if (latest.status === 'connected' && latest.connected_by_me && activeId === image.id) {
    showImage(latest);
  } else if (latest.status === 'connected') {
    showNotice(latest, '別のセッションが接続中です。このイメージは現在使用できません。');
  } else {
    await connectImage(latest);
  }
}
async function runImageAction(image, action, button) {
  if (button) { button.disabled = true; button.textContent = action === 'start' ? '起動中…' : '停止中…'; }
  try {
    const updated = await request(imageEndpoint(image.id, action), {
      method: 'POST',
      body: action === 'stop' ? sessionBody() : undefined,
    });
    if (activeId === image.id) setActiveImage(null);
    showImage(updated);
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
    if (button) button.disabled = false;
    window.alert(error.message);
  }
}
function actionButton(row, label, kind, image, action, disabled = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'image-action';
  button.dataset.kind = kind;
  button.textContent = kind === 'start' ? '▶' : kind === 'stop' ? '■' : kind === 'disconnect' ? '⏏' : '↗';
  button.title = label;
  button.setAttribute('aria-label', `${image.id}：${label}`);
  button.disabled = disabled;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    if (action === 'connect') connectImage(image);
    else if (action === 'open') selectImage(image);
    else if (activeId && activeId !== image.id) disconnectActive().then(() => runImageAction(image, action));
    else runImageAction(image, action);
  });
  row.append(button);
}
function render(nextImages) {
  images = nextImages;
  imagesElement.replaceChildren();
  imageCount.textContent = String(images.length);
  imagesEmpty.hidden = images.length > 0;
  for (const image of images) {
    const node = template.content.cloneNode(true);
    const row = node.querySelector('.image-row');
    const button = node.querySelector('.image-item');
    button.dataset.imageId = image.id;
    node.querySelector('.image-name').textContent = image.id;
    node.querySelector('.image-dot').dataset.status = image.status;
    node.querySelector('.status-label').textContent = statusLabel(image);
    button.addEventListener('click', () => selectImage(image));
    if (image.id === selectedId) button.setAttribute('aria-current', 'page');
    const actions = node.querySelector('.image-actions');
    if (image.status === 'stopped') {
      actionButton(actions, '起動', 'start', image, 'start');
    } else if (image.status === 'running') {
      actionButton(actions, '接続', 'connect', image, 'connect');
      actionButton(actions, '停止', 'stop', image, 'stop');
    } else if (image.connected_by_me) {
      actionButton(actions, '接続中の画面を表示', 'connect', image, 'open');
      actionButton(actions, '停止', 'stop', image, 'stop');
    } else {
      actionButton(actions, '別セッションが接続中', 'connect', image, 'connect', true);
      actionButton(actions, '別セッションが接続中のため停止不可', 'stop', image, 'stop', true);
    }
    imagesElement.append(node);
  }
}
async function refresh() {
  const nextImages = await request(`/manager/api/images?session_id=${encodeURIComponent(sessionId)}`);
  render(nextImages);
  return nextImages;
}

createNav.addEventListener('click', async () => {
  await disconnectActive();
  selectedId = null;
  showCreate();
});
toggleButton.addEventListener('click', () => {
  const collapsed = document.body.classList.toggle('sidebar-collapsed');
  toggleButton.setAttribute('aria-expanded', String(!collapsed));
  toggleButton.setAttribute('aria-label', collapsed ? '左メニューを開く' : '左メニューを閉じる');
  toggleButton.title = collapsed ? '左メニューを開く' : '左メニューを閉じる';
});
document.querySelector('#cancel-create').addEventListener('click', () => {
  imageIdInput.value = '';
  const selected = images.find((image) => image.id === selectedId);
  if (selected) showImage(selected);
  else showCreate();
});
createForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!createForm.reportValidity()) return;
  const requestedId = imageIdInput.value.trim();
  formError.hidden = true;
  submitCreate.disabled = true;
  submitCreate.lastChild.textContent = '作成中…';
  try {
    const image = await request('/manager/api/images', {method: 'POST', body: JSON.stringify({image_id: requestedId || null})});
    imageIdInput.value = '';
    selectedId = image.id;
    showImage(image);
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
  } finally {
    submitCreate.disabled = false;
    submitCreate.lastChild.textContent = '作成';
  }
});
window.addEventListener('pagehide', () => {
  if (!activeId) return;
  const id = activeId;
  setActiveImage(null);
  navigator.sendBeacon(imageEndpoint(id, 'disconnect'), new Blob([sessionBody()], {type: 'application/json'}));
});
let receivedInitialSnapshot = false;
const eventSource = new EventSource(`/manager/api/events?session_id=${encodeURIComponent(sessionId)}`);
eventSource.addEventListener('images', (event) => {
  const nextImages = JSON.parse(event.data);
  render(nextImages);
  if (!receivedInitialSnapshot) {
    receivedInitialSnapshot = true;
    const previousId = sessionStorage.getItem('agent-sandbox-active-image');
    const previousImage = nextImages.find((image) => image.id === previousId);
    if (previousImage && previousImage.status === 'running') connectImage(previousImage);
    else if (previousImage && previousImage.connected_by_me) {
      setActiveImage(previousImage.id);
      showImage(previousImage);
    }
  }
  if (activeId) {
    const activeImage = nextImages.find((image) => image.id === activeId);
    if (!activeImage || !activeImage.connected_by_me) {
      setActiveImage(null);
      if (selectedId === activeId && activeImage) {
        showNotice(activeImage, '接続が終了しました。必要であれば再接続してください。');
      }
    }
  }
});
eventSource.onerror = () => {
  // EventSource reconnects automatically; the server releases the session if the stream closes.
};
