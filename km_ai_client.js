/**
 * Kingdom Match AI Client — v0.1
 * Интегрирует AI-противника, генератор уровней и NPC в игру.
 * 
 * Подключение: <script src="km_ai_client.js"></script>
 * Требует запущенный AI-сервер на http://localhost:5050
 *
 * Добавляет в Game:
 *   Game.ai.enabled          — AI активен
 *   Game.ai.bot              — текущий бот-противник
 *   Game.ai.botCooldown      — ходов до следующей атаки
 *   Game.ai.quests[]         — активные квесты
 *   Game.ai.checkBotAttack() — проверка и запуск атаки бота
 *   Game.ai.talkToNPC(id)    — диалог с NPC
 *   Game.ai.generateLevels() — генерация AI-уровней
 */

(function() {
  'use strict';

  const AI_CONFIG = {
    // Базовый URL AI-сервера. Приоритет: window.KM_AI_BASE → production HTTPS → LAN hostname:5050.
    baseUrl: (function(){
      try{
        if (typeof window !== 'undefined' && window.KM_AI_BASE) return window.KM_AI_BASE;
        const h = (typeof window!=='undefined' && window.location && window.location.hostname) || 'localhost';
        // Если страница на HTTPS — AI-сервер должен быть тоже на HTTPS (CORS+mixed content)
        if (typeof window !== 'undefined' && window.location && window.location.protocol === 'https:') {
          // Без явного KM_AI_BASE на HTTPS-домене считаем AI недоступным (fallback на локальную имитацию)
          return '';
        }
        return 'http://' + h + ':5050';
      }catch(e){ return 'http://localhost:5050'; }
    })(),
    // Задержка между атаками бота (в ходах, сервер может переопределить)
    defaultCooldown: 5,
    // Показывать ли AI-интерфейс
    enabled: true,
    // Имитировать AI локально если сервер недоступен
    fallbackLocal: true,
  };

  // ============== AI MODULE ==============

  const AI = {
    enabled: AI_CONFIG.enabled,
    serverOnline: false,
    bot: null,
    botCooldown: 0,
    levelsSinceLastAttack: 0,
    quests: [],
    activeNPC: null,

    async init() {
      this.serverOnline = await this.ping();
      if (!this.serverOnline && AI_CONFIG.fallbackLocal) {
        console.log('[AI] Сервер недоступен — использую локальный fallback');
      }
      console.log('[AI] Инициализирован. Сервер:', this.serverOnline ? 'онлайн' : 'офлайн (fallback)');
    },

    async ping() {
      if (!AI_CONFIG.baseUrl) return false;
      try {
        const resp = await fetch(AI_CONFIG.baseUrl + '/api/status');
        return resp.ok;
      } catch (e) {
        return false;
      }
    },

    async apiCall(endpoint, data = {}) {
      if (this.serverOnline) {
        try {
          const resp = await fetch(AI_CONFIG.baseUrl + endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
          });
          if (resp.ok) return await resp.json();
          console.warn('[AI] Ошибка сервера:', resp.status);
        } catch (e) {
          console.warn('[AI] Сервер недоступен:', e.message);
          this.serverOnline = false;
        }
      }
      return null;
    },

    // ----- BOT OPPONENT -----

    async createBot() {
      const s = Game.state;
      if (!s.kingdom) return;

      const data = {
        kingdom: s.kingdom,
        player_level: s.level,
        difficulty: AI_CONFIG.difficulty || 'medium',
        bot_action: 'create',
      };

      if (this.serverOnline) {
        const resp = await this.apiCall('/api/bot-attack', data);
        if (resp) {
          this.bot = resp.bot;
          this.botCooldown = resp.cooldown || AI_CONFIG.defaultCooldown;
          return;
        }
      }

      // Локальный fallback
      this.bot = this._createLocalBot(s.kingdom, s.level);
      this.botCooldown = this._localCooldown();
    },

    async botAttack() {
      const s = Game.state;
      if (!this.bot || !s.kingdom) return null;

      const data = {
        kingdom: s.kingdom,
        player_level: s.level,
        player_hp: s.hp,
        player_defense: s.defense,
        player_resources: s.resources,
        player_era: s.era,
        difficulty: this.bot.difficulty || 'medium',
        bot_action: 'attack',
      };

      if (this.serverOnline) {
        const resp = await this.apiCall('/api/bot-attack', data);
        if (resp) {
          this.bot = resp.bot;
          this.botCooldown = resp.next_attack_in;
          return resp.attack;
        }
      }

      // Локальный fallback
      const attack = this._localAttack(s);
      this.botCooldown = this._localCooldown();
      return attack;
    },

    checkBotAttack() {
      if (!this.enabled || !this.bot) return;
      this.levelsSinceLastAttack++;

      if (this.levelsSinceLastAttack >= this.botCooldown) {
        this.levelsSinceLastAttack = 0;
        this._triggerBotAttack();
        return;
      }
      // Предупреждение за 1 уровень до атаки — показать карту мира с подсветкой агрессора
      const left = this.botCooldown - this.levelsSinceLastAttack;
      if (left === 1 && window.UI && typeof UI.openWorld === 'function') {
        setTimeout(() => UI.openWorld(true), 800);
      }
    },

    async _triggerBotAttack() {
      const s = Game.state;
      if (!s.hp || s.hp <= 0) return;

      const attack = await this.botAttack();
      if (!attack) return;

      // Показываем модалку с информацией об атаке
      const botName = (this.bot && (this.bot.name || this.bot.bot_name)) || attack.bot_name || 'Враг';
      document.getElementById('botAttackName').textContent = botName;
      document.getElementById('botAttackNarrative').textContent = attack.narrative || '';
      document.getElementById('botAttackDmg').textContent = attack.actual_damage;
      document.getElementById('botAttackStolen').innerHTML = '';

      // Портрет врага: пытаемся найти по имени в любом королевстве, чтобы матчить и кросс-кингдомные имена
      const portraitEl = document.getElementById('botAttackPortrait');
      let img = null;
      if (Visuals.useImages && Visuals.assets && Visuals.assets.enemies) {
        const bn = (botName || '').toLowerCase();
        for (const kd of Object.keys(Visuals.assets.enemies)) {
          /* 1. Точное совпадение имени */
          let found = Visuals.assets.enemies[kd].find(e => e.name === botName);
          /* 2. Совпадение по первому слову («Тибетский царь» ↔ «Тибетский генерал») */
          if (!found) {
            found = Visuals.assets.enemies[kd].find(e => {
              const first = (e.name||'').split(/\s+/)[0].toLowerCase();
              return first && bn.indexOf(first) === 0;
            });
          }
          if (found && found.url) { img = found.url; break; }
        }
        /* 3. Если ничего не нашли — берём любого врага из пула «другого» королевства, чтоб не показывать своих */
        if (!img) {
          const others = ['rus','horde','china'].filter(k => k !== s.kingdom);
          for (const kd of others) {
            const pool = Visuals.assets.enemies[kd];
            if (pool && pool.length) {
              const pick = pool[(Game.state.level||1) % pool.length];
              if (pick && pick.url) { img = pick.url; break; }
            }
          }
        }
      }
      if (portraitEl) {
        if (img) {
          portraitEl.style.fontSize = '0';
          portraitEl.innerHTML = `<img src="${img}" alt="" onerror="this.parentElement.style.fontSize='64px';this.parentElement.textContent='🏴‍☠️'">`;
        } else {
          portraitEl.style.fontSize = '64px';
          portraitEl.innerHTML = '';
          portraitEl.textContent = '🏴‍☠️';
        }
        // Триггер анимации атаки
        portraitEl.classList.remove('attacking');
        const flash = document.getElementById('botAttackFlash');
        if (flash) flash.classList.remove('boom');
        void portraitEl.offsetWidth; // forced reflow для рестарта анимации
        portraitEl.classList.add('attacking');
        if (flash) flash.classList.add('boom');
      }

      if (attack.resources_stolen && Object.keys(attack.resources_stolen).length > 0) {
        const stolenDiv = document.getElementById('botAttackStolen');
        const era = ERAS[s.era];
        Object.entries(attack.resources_stolen).forEach(([res, amount]) => {
          const chip = document.createElement('span');
          chip.className = 'r';
          chip.innerHTML = `<span aria-hidden="true">${era.tiles[res] || res}</span><span>-${amount}</span>`;
          stolenDiv.appendChild(chip);
          s.resources[res] = Math.max(0, (s.resources[res] || 0) - amount);
        });
      }

      // Применяем урон к крепости
      s.hp = Math.max(0, s.hp - attack.actual_damage);

      // Особые эффекты
      if (attack.special_effect === 'poison') {
        Game.state.poisonTurns = 3;
      }

      Game.save();
      UI.refreshHUD();
      UI.openModal('botAttackModal');
      UI.announce && UI.announce(botName + ' атакует. Урон ' + attack.actual_damage, true);
      UI.renderKingdomIfActive();
    },

    // Локальный fallback бот
    _createLocalBot(kingdom, level) {
      const names = {
        rus: ['Половецкий хан', 'Хазарский каган', 'Печенежский вождь'],
        horde: ['Шах Хорезма', 'Сельджукский эмир', 'Кипчакский хан'],
        china: ['Чжурчжэньский воевода', 'Тибетский генерал', 'Уйгурский каган'],
      };
      const pool = names[kingdom] || names.rus;
      return {
        name: pool[Math.floor(Math.random() * pool.length)],
        difficulty: 'medium',
        strategy: ['aggressive', 'balanced', 'resource_raid'][Math.floor(Math.random() * 3)],
        power: 40 + level * 5 + Math.floor(Math.random() * 20),
      };
    },

    _localCooldown() {
      return 3 + Math.floor(Math.random() * 5);
    },

    _localAttack(s) {
      const rawDmg = Math.floor(this.bot.power * (0.3 + Math.random() * 0.9));
      const defFactor = Math.max(0.1, 1 - s.defense / (s.defense + 100));
      const actualDmg = Math.max(1, Math.floor(rawDmg * defFactor));
      const stolen = {};
      if (Math.random() < 0.4) {
        const resKeys = Object.keys(s.resources);
        const res = resKeys[Math.floor(Math.random() * resKeys.length)];
        if (s.resources[res] > 2) {
          stolen[res] = Math.max(1, Math.floor(s.resources[res] * 0.1));
        }
      }
      return {
        bot_name: this.bot.name,
        strategy: this.bot.strategy,
        actual_damage: actualDmg,
        resources_stolen: stolen,
        special_effect: null,
        narrative: `⚔️ **${this.bot.name}** атакует крепость!\n🛡️ Нанесено **${actualDmg}** урона.` +
          (Object.keys(stolen).length ? `\n📦 Украдено ресурсов: ${JSON.stringify(stolen)}` : ''),
      };
    },

    // ----- NPC -----

    async talkToNPC(npcId) {
      this.activeNPC = npcId;
      const s = Game.state;
      const data = {
        npc_id: npcId,
        player_state: {
          level: s.level, era: s.era,
          hp: s.hp, hp_max: s.hpMax, defense: s.defense,
          coins: s.coins, resources: s.resources,
        },
        context: 'greeting',
        use_ai: this.serverOnline,
      };

      if (this.serverOnline) {
        const resp = await this.apiCall('/api/npc-dialogue', data);
        if (resp) {
          document.getElementById('npcReply').textContent = resp.reply;
          document.getElementById('npcName').textContent = resp.npc.name;
          this._setNpcAvatar(npcId, Game.state.kingdom, resp.npc.avatar);
          UI.openModal('npcModal');
          return;
        }
      }

      // Локальный fallback
      const localNPCs = this._getLocalNPCs();
      const npc = localNPCs[npcId];
      if (npc) {
        document.getElementById('npcReply').textContent = npc.hello || 'Приветствую, правитель!';
        document.getElementById('npcName').textContent = npc.name;
        this._setNpcAvatar(npcId, Game.state.kingdom, npc.avatar);
        UI.openModal('npcModal');
      }
    },

    async requestQuest(npcId) {
      /* Безопасный фоллбек по активному королевству — никогда не возвращаемся к Велимиру */
      const kCur = Game.state.kingdom || 'rus';
      const localNPCs = this._getLocalNPCs();
      if (!npcId || !localNPCs[npcId]) {
        npcId = this.activeNPC && localNPCs[this.activeNPC]
          ? this.activeNPC
          : Object.keys(localNPCs)[0];
      }
      this.activeNPC = npcId;
      const npc = localNPCs[npcId];

      /* Один совет по постройке на NPC — выдаём из локальной базы независимо от сервера */
      const state = Game.state;
      if (!state.npcAdviceGiven) state.npcAdviceGiven = {};
      const adviceKey = kCur + ':' + npcId;
      if (!state.npcAdviceGiven[adviceKey] && npc.building) {
        const meta = npc.building;
        const quest = (typeof Quests !== 'undefined' && Quests.create)
          ? Quests.create(npcId, npc, kCur, 'building', meta)
          : null;
        state.npcAdviceGiven[adviceKey] = true;
        if (typeof Game.save === 'function') Game.save();
        const goalLine = quest && quest.goal ? `\nЦель: ${quest.goal.label}` : '';
        document.getElementById('npcReply').textContent =
          `🏗️ Главный совет от ${npc.name}:\n${meta.title}\n${meta.desc}${goalLine}\nНаграда: ${meta.coins}🪙`;
        document.getElementById('npcName').textContent = npc.name;
        this._setNpcAvatar(npcId, kCur, npc.avatar);
        UI.openModal('npcModal');
        return;
      }

      /* Совет по постройке уже выдан — пробуем сервер за «настоящим» квестом */
      const data = {
        npc_id: npcId,
        player_level: Game.state.level,
        player_resources: Game.state.resources,
      };
      if (this.serverOnline) {
        const resp = await this.apiCall('/api/npc-quest', data);
        if (resp && resp.quest) {
          /* Маппим серверный квест в нашу систему прогресса и сохраняем в state.quests */
          let questObj = null;
          if (typeof Quests !== 'undefined' && Quests.fromServer) {
            questObj = Quests.fromServer(npcId, (resp.npc || npc), kCur, resp.quest);
          }
          const goalLine = questObj && questObj.goal ? `\nЦель: ${questObj.goal.label}` : '';
          document.getElementById('npcReply').textContent =
            `📜 Новый квест: ${resp.quest.title}\n${resp.quest.description}${goalLine}\nНаграда: ${resp.quest.reward_coins}🪙`;
          document.getElementById('npcName').textContent = (resp.npc && resp.npc.name) || npc.name;
          this._setNpcAvatar(npcId, kCur, (resp.npc && resp.npc.avatar) || npc.avatar);
          UI.openModal('npcModal');
          return;
        }
      }

      /* Сервер недоступен или отказал — выдаём случайную подсказку из локального пула */
      const pool = npc.tips && npc.tips.length
        ? npc.tips
        : [{ title:'Полезный совет', desc:'Собирай matches-4 — дают бонусные ресурсы.', coins:60 }];
      const meta = pool[Math.floor(Math.random() * pool.length)];
      const quest = (typeof Quests !== 'undefined' && Quests.create)
        ? Quests.create(npcId, npc, kCur, 'tip', meta)
        : null;
      const goalLine = quest && quest.goal ? `\nЦель: ${quest.goal.label}` : '';
      document.getElementById('npcReply').textContent =
        `💡 Совет от ${npc.name}:\n${meta.title}\n${meta.desc}${goalLine}\nНаграда: ${meta.coins}🪙`;
      document.getElementById('npcName').textContent = npc.name;
      this._setNpcAvatar(npcId, kCur, npc.avatar);
      UI.openModal('npcModal');
    },

    _getLocalNPCs() {
      const k = Game.state.kingdom || 'rus';
      const npcs = {
        rus: {
          velimir: {
            name:'Старец Велимир', avatar:'🧙',
            hello:'Здрав буди, княже! Что тревожит душу твою?',
            building:{ title:'Возведи каменные стены', desc:'Построй стены в крепости — они отразят первый удар степи.', coins:250 },
            tips:[
              { title:'Терпение, княже', desc:'Не растрачивай жизни на тяжёлый уровень. Дождись восстановления и атакуй на свежую голову.', coins:60 },
              { title:'Сила в комбинациях', desc:'Совмещай 4 одинаковых руны в ряд — получишь бонусные ресурсы и больший урон.', coins:80 },
              { title:'Молись о ходах', desc:'Если ход не даёт совпадений — лучше использовать «перемешать», чем терять время.', coins:70 },
              { title:'Видеть наперёд', desc:'Сначала смотри на верх доски — после падения новых рун там часто появляются 4-в-ряд.', coins:90 },
            ]
          },
          dobrynya: {
            name:'Воевода Добрыня', avatar:'⚔️',
            hello:'Докладывай, воевода. Что на рубежах?',
            building:{ title:'Поставь сторожевые башни', desc:'Построй башни — лучники с них собьют до трети урона врага.', coins:300 },
            tips:[
              { title:'Берегите воинов', desc:'Совмещай 🗡️ только если враг близок к смерти — иначе лучше копить ресурсы.', coins:80 },
              { title:'Дозор', desc:'Перед боем посмотри карту мира — если сосед в красной угрозе, готовь оборону, а не атаку.', coins:70 },
              { title:'Засада', desc:'Бустер «бомба» лучше тратить, когда вокруг 6+ нужных рун — снесёт целый квадрат.', coins:90 },
              { title:'Строй полки', desc:'Покупай войска в магазине только перед сложным уровнем — иначе бесполезно.', coins:60 },
            ]
          },
          marfa: {
            name:'Купчиха Марфа', avatar:'👩‍🌾',
            hello:'Ой, княже! Товар заморский привезла!',
            building:{ title:'Открой торговую пристань', desc:'Построй ворота крепости — караваны принесут больше золота.', coins:220 },
            tips:[
              { title:'Дешевле в пакете', desc:'Стартовый набор окупается уже после 3 уровней — не упусти.', coins:50 },
              { title:'Скидка по средам', desc:'Реклама даёт +100🪙 после боя — смотри, если копишь на постройку.', coins:60 },
              { title:'Купи дёшево', desc:'Лучники дешевеют после открытия 3-й эпохи. Подожди — сэкономишь.', coins:70 },
              { title:'Запасы важны', desc:'Перед боем держи минимум 1 бустер каждого вида — иначе застрянешь.', coins:80 },
            ]
          }
        },
        horde: {
          batu: {
            name:'Темник Бату', avatar:'🤵',
            hello:'Сайн байна уу, хан! Какие вести из степи?',
            building:{ title:'Поставь юрты-казармы', desc:'Возведи стены крепости — без них кочевникам негде встретить врага.', coins:250 },
            tips:[
              { title:'Кочуй ходами', desc:'Если на доске нет 3-в-ряд — не торопись, разворачивай руны с краёв.', coins:70 },
              { title:'Стрелы быстрее меча', desc:'Совпадение 🏹 даёт урон дальнего боя — не теряет силы, когда враг далеко.', coins:80 },
              { title:'Степной налёт', desc:'Бустер «ряд» лучше класть на середину поля — задевает максимум рун.', coins:90 },
              { title:'Зимовка', desc:'Не штурмуй соседей в первой эпохе — потеря жизней дороже трофеев.', coins:60 },
            ]
          },
          altan: {
            name:'Алтан-шаман', avatar:'🪬',
            hello:'Духи шепчут... Ты пришёл за советом?',
            building:{ title:'Поставь духовное капище', desc:'Построй башню — духи через неё подскажут о приближении врага.', coins:280 },
            tips:[
              { title:'Знаки судьбы', desc:'Если 3 раза подряд нет матчей — перемешай. Это не невезение, это «застрявшая» доска.', coins:80 },
              { title:'Видения', desc:'Перед уровнем посмотри его номер — каждый 5-й сложнее обычного.', coins:70 },
              { title:'Связь с предками', desc:'Совпадение ✝️/📿 кроме урона добавляет очко эпохи. Не игнорируй веру.', coins:90 },
              { title:'Шаманский транс', desc:'Когда время ≤15 сек — не пытайся комбо-4. Жми любые тройки.', coins:60 },
            ]
          },
          gulnara: {
            name:'Гульнара-бегим', avatar:'👸',
            hello:'Мой караван привёз шёлк и пряности!',
            building:{ title:'Возведи базар', desc:'Открой ворота — караваны увеличат доход с каждой победы на 20%.', coins:240 },
            tips:[
              { title:'Шёлк в Поднебесную', desc:'Совпадение 💰 после 3-й эпохи приносит вдвое больше монет. Береги их.', coins:80 },
              { title:'Цена крови', desc:'Не плати за продолжение, если уровень ниже 15-го — проще переиграть.', coins:60 },
              { title:'Дары', desc:'NPC-квесты дают монеты без боя. Заходи в советники каждые 2-3 уровня.', coins:90 },
              { title:'Караван', desc:'🍞 копи на 5-ю эпоху — там еда нужна для апгрейда крепости.', coins:70 },
            ]
          }
        },
        china: {
          libo: {
            name:'Мудрец Ли Бо', avatar:'👲',
            hello:'Луна над пагодой светла... Какие думы тревожат императора?',
            building:{ title:'Возведи пагоду', desc:'Построй центральную башню — она удвоит защиту крепости.', coins:280 },
            tips:[
              { title:'Путь в тысячу ли', desc:'Не пытайся пройти 3 уровня подряд без передышки — концентрация падает.', coins:80 },
              { title:'Гармония рун', desc:'Совмещай разные стихии по очереди (огонь, вода, земля), не цепляйся за один тип.', coins:90 },
              { title:'Учение Дао', desc:'Используй «молот» только на критический руне, которая мешает 4-в-ряд.', coins:70 },
              { title:'Небеса наблюдают', desc:'Если враг почти повержен, не трать бустер — добей обычным ходом.', coins:60 },
            ]
          },
          zhen: {
            name:'Генерал Чжэнь', avatar:'🐉',
            hello:'Войско построено, император. Жду приказа.',
            building:{ title:'Построй Великую стену', desc:'Возведи стены крепости — половина урона врага рассеется о камень.', coins:320 },
            tips:[
              { title:'Тактика дракона', desc:'4-в-ряд по вертикали бьёт по «голове» врага — больше критов.', coins:90 },
              { title:'Война — обман', desc:'Бустер «перемешать» используй ДО первого хода, если доска плоха.', coins:80 },
              { title:'Резервы', desc:'Конница 🐎 копится с трудом — береги её для уровней-«боссов».', coins:70 },
              { title:'Зов крови', desc:'Если HP крепости ≤30% — играй только на оборону, не атакуй соседей.', coins:60 },
            ]
          },
          mei: {
            name:'Госпожа Мэй', avatar:'🪭',
            hello:'Тсс... у меня сведения о враге.',
            building:{ title:'Пророй скрытые тоннели', desc:'Построй ров — диверсанты пройдут под стенами и снимут осаду быстрее.', coins:260 },
            tips:[
              { title:'Уши шёлка', desc:'Каждый второй визит к NPC даёт подсказку — заходи чаще, копи знание.', coins:80 },
              { title:'Тихая нога', desc:'Покупай жизни рекламой, а не за монеты — копи на эпохальные апгрейды.', coins:60 },
              { title:'Свиток шпиона', desc:'Карта мира показывает кулдаун атаки соседей — играй за 1 уровень до удара.', coins:90 },
              { title:'Веер', desc:'Бустер «бомба» эффективнее у края поля, чем в центре — задевает меньше пустых клеток.', coins:70 },
            ]
          }
        },
      };
      return npcs[k] || npcs.rus;
    },

    // ----- LEVEL GENERATOR -----

    async generateLevels(count = 5) {
      const s = Game.state;
      const data = {
        kingdom: s.kingdom,
        era: s.era,
        start_level: s.level,
        count: count,
        difficulty: 'normal',
        use_ai: this.serverOnline,
      };

      if (this.serverOnline) {
        const resp = await this.apiCall('/api/generate-levels', data);
        if (resp) {
          document.getElementById('aiLevelsResult').textContent = 
            `✅ Сгенерировано ${resp.levels.length} AI-уровней (валидных: ${resp.validations.filter(v => v.valid).length}/${resp.validations.length})`;
          Game.aiLevels = resp.levels;
          return resp.levels;
        }
      }

      // Локальный fallback
      const levels = [];
      for (let i = 0; i < count; i++) {
        levels.push({
          id: s.level + i,
          name: `AI-уровень ${s.level + i}`,
          enemyHP: 80 + (s.level + i) * 25,
          timer: Math.max(45, 120 - Math.floor((s.level + i) / 2) * 2),
        });
      }
      document.getElementById('aiLevelsResult').textContent = 
        `✅ Сгенерировано ${count} уровней (локально)`;
      Game.aiLevels = levels;
      UI.refreshHUD();
      return levels;
    },

    openNPCList() {
      const kingdom = Game.state.kingdom || 'rus';
      const npcs = this._getLocalNPCs();
      const list = document.getElementById('npcList');
      list.innerHTML = '';
      Object.entries(npcs).forEach(([id, npc]) => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'npc-card';
        card.setAttribute('role', 'listitem');
        card.setAttribute('aria-label', npc.name);
        const img = Visuals.getNpcImg(kingdom, id);
        const avatarHtml = img
          ? `<span class="ava" aria-hidden="true" style="width:48px;height:48px;font-size:0;display:inline-flex;border-radius:50%;overflow:hidden;border:2px solid rgba(255,255,255,.2);box-shadow:0 2px 6px rgba(0,0,0,.5);flex-shrink:0"><img src="${img}" alt="" style="width:100%;height:100%;object-fit:cover" onerror="this.parentElement.style.fontSize='36px';this.parentElement.textContent='${npc.avatar}'"></span>`
          : `<span class="ava" aria-hidden="true">${npc.avatar}</span>`;
        card.innerHTML = avatarHtml + `<b>${npc.name}</b>`;
        card.onclick = () => this.talkToNPC(id);
        list.appendChild(card);
      });
      UI.show('npcScreen');
    },

    /* Поставить аватар (изображение или эмодзи) в #npcAva */
    _setNpcAvatar(npcId, kingdom, fallbackEmoji) {
      const ava = document.getElementById('npcAva');
      if (!ava) return;
      const img = Visuals.getNpcImg(kingdom || Game.state.kingdom || 'rus', npcId);
      if (img) {
        ava.style.fontSize = '0';
        ava.innerHTML = `<img src="${img}" alt="" style="width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #ffd86b;box-shadow:0 3px 8px rgba(0,0,0,.6);display:block" onerror="this.parentElement.style.fontSize='36px';this.parentElement.textContent='${fallbackEmoji||'🎭'}'">`;
      } else {
        ava.style.fontSize = '';
        ava.textContent = fallbackEmoji || '🎭';
      }
    },
  };

  // ============== ИНТЕГРАЦИЯ ==============

  // Хук: после инициализации игры запускаем AI
  const origInit = Game.init;
  Game.init = function() {
    origInit.call(this);
    if (AI_CONFIG.enabled) {
      AI.init().then(() => {
        if (this.state.kingdom) {
          AI.createBot();
          Visuals.load().then(() => {
            if (Visuals.useImages) Visuals.applyKingdomBg();
          });
        }
      });
    }
    this.ai = AI;
  };

  // Хук: после выбора королевства создаём бота
  const origSelectKingdom = Game.selectKingdom;
  Game.selectKingdom = function(k) {
    origSelectKingdom.call(this, k);
    if (AI.enabled) {
      setTimeout(() => Comic.show(k, 'kingdom_select'), 700);
      AI.createBot();
      if (!Visuals.loaded) {
        Visuals.load().then(() => {
          if (Visuals.useImages) Visuals.applyKingdomBg();
        });
      }
    }
  };

  // Хук: после победы на уровне проверяем бота
  const origAfterWin = Game.afterWin;
  Game.afterWin = function() {
    origAfterWin.call(this);
    if (AI.enabled) {
      AI.checkBotAttack();
    }
  };

  // Хук: после выхода с уровня (поражение)
  const origExitLevel = Game.exitLevel;
  Game.exitLevel = function() {
    origExitLevel.call(this);
    if (AI.enabled) {
      AI.checkBotAttack();
    }
  };

  // Хук: после рендера королевства — применяем фоны
  const origRenderKingdom = UI.renderKingdom;
  UI.renderKingdom = function() {
    origRenderKingdom.call(this);
    if (Visuals.useImages) {
      Visuals.applyKingdomBg();
      setTimeout(() => Visuals.applyFortress(), 100);
    }
  };

  // Хук: после рендера игровой темы — применяем врага
  const origRenderGameTheme = UI.renderGameTheme;
  UI.renderGameTheme = function() {
    origRenderGameTheme.call(this);
    if (Visuals.useImages) {
      Visuals.applyEnemyToGame();
      Visuals.applyKingdomBg();
    }
  };

  /* Board сам красит иконки через _paintIcon; здесь ничего дублировать не нужно.
     Но после первой загрузки ассетов перекрашиваем уже-заспавненные тайлы. */

  // ============== REPLICATE VISUALS ==============

  const Visuals = {
    assets: null,
    loaded: false,
    /* В Capacitor (мобильный APK) AI-арт включаем только по кнопке — 64 параллельных
       PNG-загрузки по LAN затыкают главный поток и приводят к ANR. На обычном web — включён. */
    useImages: !(typeof window !== 'undefined' && window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()),

    async load() {
      try {
        const resp = await fetch(AI_CONFIG.baseUrl + '/api/assets');
        if (resp.ok) {
          this.assets = await resp.json();
          this.loaded = true;
          console.log('[Visuals] ' +
            (this.assets.enemies ? Object.values(this.assets.enemies).flat().length : 0) + ' enemies, ' +
            (this.assets.kingdom_bgs ? Object.keys(this.assets.kingdom_bgs).length : 0) + ' bgs loaded');
          /* Если доска уже отрисована — перекрасить иконки на AI-арт */
          if (typeof Board !== 'undefined' && Board.repaintIcons && Board.grid && Board.grid.length) {
            try { Board.repaintIcons(); } catch (e) {}
          }
          return true;
        }
      } catch (e) {
        console.log('[Visuals] Server not available:', e.message);
      }
      return false;
    },

    toggle() {
      this.useImages = !this.useImages;
      UI.renderKingdom();
      UI.renderMap();
      /* Перерисовать тайлы — переключение «эмодзи ↔ AI-арт» */
      if (typeof Board !== 'undefined' && Board.repaintIcons) {
        try { Board.repaintIcons(); } catch (e) {}
      }
      return this.useImages;
    },

    getEnemyImg(kingdom, enemyName) {
      if (!this.useImages || !this.assets?.enemies?.[kingdom]) return null;
      const found = this.assets.enemies[kingdom].find(e => e.name === enemyName);
      return found?.url || null;
    },

    getKingdomBg(kingdom) {
      if (!this.useImages || !this.assets?.kingdom_bgs?.[kingdom]) return null;
      return this.assets.kingdom_bgs[kingdom];
    },

    getEraBg(era) {
      if (!this.useImages || !this.assets?.era_bgs) return null;
      const found = this.assets.era_bgs.find(e => e.era === era);
      return found?.url || null;
    },

    getTileImg(tileType, era) {
      if (!this.useImages || !this.assets || !this.assets.tiles || !this.assets.tiles[tileType]) return null;
      const list = this.assets.tiles[tileType];
      if (!list.length) return null;
      /* Точное совпадение эпохи или ближайшая нижняя */
      let match = list.find(e => e.era === era);
      if (!match) {
        const sorted = [...list].sort((a, b) => a.era - b.era);
        match = sorted.filter(e => e.era <= era).pop() || sorted[sorted.length - 1];
      }
      return match && match.url ? match.url : null;
    },

    getNpcImg(kingdom, npcId) {
      if (!this.useImages || !this.assets?.npcs?.[kingdom]) return null;
      const found = this.assets.npcs[kingdom].find(n => n.id === npcId);
      return found?.url || null;
    },

    /* Выбрать «вражеское» королевство — всегда отличное от собственного,
       и ротировать его по номеру уровня, чтобы враги были визуально разнообразными. */
    _otherKingdoms(own) {
      return ['rus','horde','china'].filter(k => k !== own);
    },
    pickEnemyForLevel() {
      if (!this.assets || !this.assets.enemies) return null;
      const s = Game.state;
      const own = s.kingdom || 'rus';
      const levelId = (Game.currentLevel && Game.currentLevel.id) || s.level || 1;
      const others = this._otherKingdoms(own);
      /* Ротация: уровни 1,4,7 → others[0]; 2,5,8 → others[1]; и т.д. */
      const targetKd = others[(levelId - 1) % others.length];
      const pool = this.assets.enemies[targetKd] || [];
      if (!pool.length) return null;
      const pick = pool[(levelId - 1) % pool.length];
      return pick ? { ...pick, kingdom: targetKd } : null;
    },

    applyEnemyToGame() {
      if (!this.useImages || !this.assets) return;
      const enemy = this.pickEnemyForLevel();
      const fig = document.getElementById('enemyFigure');
      const nameEl = document.getElementById('enemyName');
      if (enemy) {
        if (fig) {
          fig.innerHTML = `<img src="${enemy.url}" alt="" style="width:60px;height:60px;border-radius:50%;object-fit:cover;border:2px solid #e63946;box-shadow:0 4px 10px rgba(0,0,0,.6)" onerror="this.parentElement.style.fontSize='50px';this.parentElement.textContent='👹'">`;
          fig.style.fontSize = '0';
        }
        if (nameEl) nameEl.textContent = enemy.name;
      }
    },

    applyKingdomBg() {
      if (!this.useImages || !this.assets) return;
      const s = Game.state;
      const bg = this.getKingdomBg(s.kingdom);
      if (bg) {
        const kbg = document.getElementById('kbg');
        if (kbg) { kbg.style.backgroundImage = `url(${bg})`; kbg.style.backgroundSize = 'cover'; kbg.style.backgroundPosition = 'center'; }
      }
      const eraBg = this.getEraBg(s.era);
      if (eraBg) {
        const gbg = document.getElementById('gbg');
        if (gbg) gbg.style.backgroundImage = `url(${eraBg})`;
      }
    },

    applyTiles() {
      /* Тонкий шим для обратной совместимости — реальная работа в Board.repaintIcons() */
      if (typeof Board !== 'undefined' && Board.repaintIcons) {
        Board.repaintIcons();
      }
    },

    applyFortress() {
      if (!this.useImages || !this.assets?.fortress) return;
      const f = this.assets.fortress;
      // У каждой постройки своя «форма»: квадратные PNG обрезаем под силуэт здания
      const slots = [
        { key:'castle', sel:'.iso-bld.castle .sprite', w:1.4, h:1.4, clip:'inset(0)' },
        { key:'tower',  sel:'.iso-bld.tower .sprite',  w:0.9, h:1.5, clip:'inset(0 22% 0 22%)' },
        { key:'walls',  sel:'.iso-bld.wall .sprite',   w:1.6, h:0.9, clip:'inset(30% 0 10% 0)' },
        { key:'gate',   sel:'.iso-bld.gate .sprite',   w:1.1, h:1.1, clip:'inset(8% 12% 0 12%)' }
      ];
      slots.forEach(s => {
        if (!f[s.key]) return;
        document.querySelectorAll(s.sel).forEach(el => {
          if (el.querySelector('img')) return;
          const size = parseFloat(getComputedStyle(el).fontSize) || 48;
          const w = Math.round(size * s.w);
          const h = Math.round(size * s.h);
          el.style.fontSize = '0';
          el.innerHTML = `<img src="${f[s.key]}" style="width:${w}px;height:${h}px;display:block;object-fit:cover;clip-path:${s.clip}" onerror="this.parentElement.style.fontSize='${size}px';this.remove()">`;
        });
      });
    },
  };

  Game.visuals = Visuals;

  // ============== COMIC ==============

  window.Comic = {
    panels: [],
    current: 0,
    story: null,

    async show(kingdom, trigger) {
      kingdom = kingdom || Game.state.kingdom || 'rus';
      trigger = trigger || 'kingdom_select';
      this._kingdom = kingdom;

      /* Подгружаем ассеты, если ещё не загружены — нужны для фоновых картинок */
      if (!Visuals.loaded) {
        try { await Visuals.load(); } catch(e) {}
      }

      try {
        const resp = await fetch(AI_CONFIG.baseUrl + `/api/comic-story?kingdom=${kingdom}&trigger=${trigger}&level=${Game.state.level}&era=${Game.state.era}`);
        if (resp.ok) this.story = await resp.json();
      } catch(e) {}

      if (!this.story || !this.story.panels || !this.story.panels.length) {
        this.story = this._localStory(kingdom);
      }

      this.panels = this.story.panels;
      this.current = 0;
      this._renderDots();
      this._renderPanel();
      UI.show('comicScreen');
    },

    /* Подбираем эмодзи-аватар по имени спикера и королевству */
    _speakerEmoji(speaker, kingdom) {
      if (!speaker || speaker === 'Narrator') {
        const k = (typeof KINGDOMS!=='undefined') && KINGDOMS[kingdom];
        return k && k.enemyIcon ? k.enemyIcon : '📜';
      }
      const k = (typeof KINGDOMS!=='undefined') && KINGDOMS[kingdom];
      if (k && k.guide && (speaker === k.guide.name || speaker.indexOf(k.guide.name.split(' ').pop()) >= 0)) {
        return k.guide.ava;
      }
      /* По ключевым словам */
      const s = speaker.toLowerCase();
      if (s.includes('хан') || s.includes('темник') || s.includes('бату')) return '🤵';
      if (s.includes('император') || s.includes('мудрец') || s.includes('ли бо')) return '👲';
      if (s.includes('старец') || s.includes('велимир') || s.includes('князь')) return '🧙';
      if (s.includes('воевод') || s.includes('генерал')) return '⚔️';
      return '🎭';
    },

    /* Собираем визуальную панель из имеющихся ассетов сервера, если image_url пуст */
    _composePanelImg(panel, kingdom) {
      const bg = Visuals.getKingdomBg(kingdom) || Visuals.getEraBg(Game.state.era);
      const speaker = panel.speaker || '';
      const ava = this._speakerEmoji(speaker, kingdom);
      /* Для повествования (Narrator) пробуем подложить вражеский портрет, чтобы было динамичнее */
      let portraitImg = '';
      if (speaker === 'Narrator' && Visuals.assets && Visuals.assets.enemies && Visuals.assets.enemies[kingdom]) {
        const list = Visuals.assets.enemies[kingdom];
        if (list && list.length) {
          const pick = list[(this.current || 0) % list.length];
          if (pick && pick.url) {
            portraitImg = `<img src="${pick.url}" alt="" style="position:absolute;right:8%;bottom:8%;height:55%;border-radius:10px;border:3px solid #ffd86b;box-shadow:0 6px 16px rgba(0,0,0,.6);object-fit:cover">`;
          }
        }
      }
      const bgLayer = bg
        ? `<img src="${bg}" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:saturate(1.05) contrast(1.05)">`
        : `<div style="position:absolute;inset:0;background:linear-gradient(135deg,#3b1d6b,#1a0d33)"></div>`;
      const tintLayer = `<div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 30%,rgba(0,0,0,.55) 100%)"></div>`;
      return `<div style="position:relative;width:100%;aspect-ratio:4/3;min-height:200px;overflow:hidden;border-radius:5px;background:#1a0d33">${bgLayer}${portraitImg}${tintLayer}</div>`;
    },

    _localStory(k) {
      const tpl = {
        rus: {title:'Князь и Степь', panels:[
          {layout:'top_banner',caption:'Русь, XII век',speaker:'Старец Велимир',dialogue:'Княже! Враг у ворот. Возьми меч предков!',image_prompt:''},
          {layout:'full',speaker:'Narrator',dialogue:'Так начинается путь... От частокола до каменных стен.',image_prompt:''},
        ]},
        horde: {title:'Хан Великой Степи', panels:[
          {layout:'top_banner',caption:'Великая Степь, XIII век',speaker:'Темник Бату',dialogue:'Хан! Твои тумены ждут. Покажи врагу силу Орды!',image_prompt:''},
          {layout:'full',speaker:'Narrator',dialogue:'От юрты до дворца. Степь помнит героев.',image_prompt:''},
        ]},
        china: {title:'Император Поднебесной', panels:[
          {layout:'top_banner',caption:'Империя Тан',speaker:'Мудрец Ли Бо',dialogue:'Император! Путь в тысячу ли — с первого шага.',image_prompt:''},
          {layout:'full',speaker:'Narrator',dialogue:'От бамбука до Великой стены. Небеса наблюдают.',image_prompt:''},
        ]},
      };
      return tpl[k] || tpl.rus;
    },

    _renderPanel() {
      const p = this.panels[this.current];
      if (!p) return;
      document.getElementById('comicTitle').textContent = '📖 ' + (this.story.title || 'ХРОНИКИ');
      const cap = document.getElementById('comicCaption');
      if (p.caption) { cap.style.display = 'block'; cap.textContent = p.caption; }
      else cap.style.display = 'none';
      document.getElementById('comicSpeaker').textContent = p.speaker === 'Narrator' ? '' : p.speaker + ': ';
      document.getElementById('comicDialogue').textContent = p.dialogue;
      const imgEl = document.getElementById('comicImg');
      if (p.image_url) {
        imgEl.innerHTML = `<img src="${p.image_url}" alt="" style="width:100%;height:100%;object-fit:cover">`;
      } else {
        imgEl.innerHTML = this._composePanelImg(p, this._kingdom || Game.state.kingdom || 'rus');
      }
      imgEl.style.fontSize = '0';
      /* Обновляем aria-label панели описанием спикера/реплики */
      imgEl.setAttribute('aria-label', (p.speaker && p.speaker!=='Narrator' ? p.speaker+'. ' : '') + (p.dialogue||''));
      imgEl.removeAttribute('aria-hidden');
      document.getElementById('comicPrev').disabled = this.current === 0;
      document.getElementById('comicNext').textContent = this.current >= this.panels.length - 1 ? 'ЗАКРЫТЬ' : 'ВПЕРЁД ▶';
      this._renderDots();
    },

    _renderDots() {
      const dots = document.getElementById('comicDots');
      dots.innerHTML = this.panels.map((_, i) => `<div class="dot${i === this.current ? ' active' : ''}"></div>`).join('');
    },

    next() {
      if (this.current >= this.panels.length - 1) { this.close(); return; }
      this.current++;
      this._renderPanel();
    },
    prev() { if (this.current > 0) { this.current--; this._renderPanel(); } },
    close() { UI.show('kingdom'); UI.renderKingdom(); },
  };

  console.log('[AI] Kingdom Match AI Client v0.1 загружен');
})();