/* The legacy PC client sends the list and resolves parcels through InboxReader. */
(function () {
    "use strict";
    var doc = document, list = doc.getElementById("list"), status = doc.getElementById("status");
    var claim = doc.getElementById("claim"), all = doc.getElementById("select-all");
    var refresh = doc.getElementById("refresh"), close = doc.getElementById("close");
    var choices = [], busy = false, submitted = false, ticket = 0;
    var owns = Object.prototype.hasOwnProperty;

    function element(tag, className, text) {
        var node = doc.createElement(tag);
        if (className) { node.className = className; }
        if (typeof text !== "undefined") { node.appendChild(doc.createTextNode(String(text))); }
        return node;
    }

    function tell(message) { status.textContent = message; }

    function proxy() { return window.parent.unityProxy; }

    function closePage() {
        try {
            proxy().close();
        } catch (err) {
            tell("无法连接游戏。请从游戏内打开收件箱。");
        }
    }

    function updateButtons() {
        var selected = 0, locked = busy || submitted;
        for (var i = 0; i < choices.length; i++) {
            var choice = choices[i];
            if (choice.box.checked) { selected++; }
            choice.row.className = choice.style + (choice.box.checked ? " selected" : "");
            choice.box.disabled = locked;
            choice.button.disabled = locked;
        }
        all.disabled = locked || !choices.length;
        all.textContent = selected && selected === choices.length ? "取消全选" : "全选";
        claim.disabled = locked || !selected;
        claim.textContent = selected ? "领取所选（" + selected + "）" : "领取所选";
        refresh.disabled = locked;
    }

    function drawRewards(container, data) {
        var rewards = data.rewards || {};
        var captions = Object.keys(rewards);
        var items = element("ul", "rewards");
        for (var i = 0; i < captions.length; i++) {
            var caption = captions[i];
            var parts = /^(.*) x([0-9]+)$/.exec(caption);
            var item = element("li", "reward");
            var icon = element("span", "reward-icon");
            var info = element("div", "reward-details");
            var path = rewards[caption];
            if (typeof path === "string" && /^assets\/item\/[0-9a-f]{8}\/[0-9a-f]{8}\.png$/i.test(path)) {
                var image = element("img");
                image.alt = "";
                image.onerror = function () {
                    this.parentNode.title = "图标缺失";
                    this.parentNode.removeChild(this);
                };
                icon.appendChild(image);
                image.src = "../" + path;
            } else {
                icon.title = "图标缺失";
            }
            if (i === 0) {
                info.appendChild(element("strong", "parcel-sender", data.name || "包裹"));
                if (data.createdTime) { info.appendChild(element("time", "parcel-time", data.createdTime)); }
            }
            var label = element("span", "reward-caption", parts ? parts[1] : caption);
            if (parts) { label.appendChild(element("span", "reward-count", " ×" + parts[2])); }
            info.appendChild(label);
            item.appendChild(icon);
            item.appendChild(info);
            items.appendChild(item);
        }
        container.appendChild(items);
    }

    function drawParcel(id, data) {
        var style = "parcel" + (data.text ? " has-note" : "");
        var row = element("article", style);
        var actions = element("div", "parcel-actions");
        var button = element("button", "", "领取报酬");
        button.type = "button";
        button.onclick = function () { submit([id]); };
        actions.appendChild(button);
        var mark = element("label", "parcel-select"), box = element("input");
        box.type = "checkbox";
        box.onchange = updateButtons;
        mark.appendChild(box);
        mark.appendChild(doc.createTextNode("选择"));
        actions.appendChild(mark);
        row.appendChild(actions);

        var content = element("div", "parcel-main");
        drawRewards(content, data);
        row.appendChild(content);
        if (data.text) { row.appendChild(element("div", "parcel-note", data.text)); }
        list.appendChild(row);
        choices.push({id: id, row: row, style: style, box: box, button: button});
    }

    function draw(result) {
        if (!result || !result.parcels || !Array.isArray(result.index)) {
            tell("包裹列表读取失败，请刷新或返回游戏。");
            return;
        }
        list.textContent = "";
        choices = [];
        var parcels = result.parcels, ids = result.index;
        for (var i = 0; i < ids.length; i++) {
            var id = ids[i];
            if (typeof id === "string" && owns.call(parcels, id) && parcels[id]) {
                drawParcel(id, parcels[id]);
            }
        }
        tell(choices.length ? choices.length + " 件待领取" : "");
        if (!choices.length) { list.appendChild(element("p", "empty", "没有待领取的包裹。")); }
    }

    function reload() {
        if (busy || submitted) { return; }
        busy = true;
        updateButtons();
        tell("正在读取包裹…");
        var current = ++ticket;
        function finish(result) {
            if (current !== ticket) { return; }
            ++ticket;
            busy = false;
            draw(result);
            updateButtons();
        }
        var timer = window.setTimeout(function () { finish(null); }, 8000);
        try {
            proxy().send("reload", {start: 0, end: -1}, function (result) {
                window.clearTimeout(timer);
                finish(result);
            });
        } catch (err) {
            window.clearTimeout(timer);
            finish(null);
        }
    }

    function submit(ids) {
        if (busy || submitted || !ids.length) { return; }
        var responses = Object.create(null);
        for (var i = 0; i < ids.length; i++) { responses[ids[i]] = "accept"; }
        submitted = true;
        updateButtons();
        tell("已交给游戏处理领取请求…");
        var timer = window.setTimeout(function () {
            tell("未收到游戏确认。请返回游戏后重新打开收件箱查看结果。");
        }, 8000);
        try {
            proxy().send("resolve", responses, function () {
                window.clearTimeout(timer);
                // InboxReader acknowledges dispatch immediately, then Unity applies the reward.
                closePage();
            });
        } catch (err) {
            window.clearTimeout(timer);
            tell("无法确认领取请求。请返回游戏后重新查看包裹。");
        }
    }

    all.onclick = function () {
        if (busy || submitted) { return; }
        var check = false;
        for (var i = 0; i < choices.length; i++) { check = check || !choices[i].box.checked; }
        for (i = 0; i < choices.length; i++) { choices[i].box.checked = check; }
        updateButtons();
    };
    claim.onclick = function () {
        var selected = [];
        for (var i = 0; i < choices.length; i++) {
            if (choices[i].box.checked) { selected.push(choices[i].id); }
        }
        submit(selected);
    };

    close.onclick = closePage;
    refresh.onclick = reload;
    reload();
}());
