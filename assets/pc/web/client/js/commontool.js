// リスナー登录
var ListenerRegister = function(){
	return {
		register : function( type, handler ) {
			if (window.addEventListener)
				window.addEventListener( type, handler, false);
			else if (window.attachEvent)
				window.attachEvent( "on" + type, handler);	
		},
		unregister : function( type, handler ) {
			if (window.removeEventListener)
				window.removeEventListener( type, handler, false);
			else if (window.detachEvent1)
				window.attachEvent( "on" + type, handler);	
		}
	};
};

// 泛用マウスオーバーメッセージウィンドウ
var MouseOverMsgWindow = function( root, id ) {
	// root: ウィンドウの基点となるjQueryオブジェクト
	var me = this;
	this.root = root;
	
	// ウィンドウ领域（デフォルトでは基点にアタッチしない）
	this.rootDiv = $("<div/>").attr({id:id}).css({
		position:"absolute",
		left: 0,
		top: 0,
		width: 64,
		height: 64
	});
	
	var bg = $("<img/>").attr({src:"../img/popupwindow01.png"}).
		css({position:"absolute", left:0, top:0, "z-index":100});
	this.rootDiv.append( bg );
	
	// ウィンドウ描画位置设定
	this.setPos = function( ofsX, ofsY ) {
		me.rootDiv.css( "left", ofsX );
		me.rootDiv.css( "top", ofsY );
	}
	
	// 大きさを设定
	this.setWH = function( width, height ) {
		me.rootDiv.css( "width", width );
		me.rootDiv.css( "height", height );
	}
	
	// 基点にアタッチ（表示）
	this.show = function( e ) {
		if ( root.find("#" + id ).length > 0 )
			return;	// 既に表示
		console.log( "In!" );
		root.append( me.rootDiv );
	}
	
	// 基点からでタッチ（非表示）
	this.hide = function( e ) {
		console.log( 
			"ofsX: " + e.offsetX + 
			" W: " + e.fromElement.clientWidth + 
			" ofsY: " + e.offsetY +
			" H: " + e.fromElement.clientHeight
		);
		if ( e.offsetX <= 0 ||
			 e.offsetX >= e.fromElement.clientWidth ||
			 e.offsetY <= 0 ||
			 e.offsetY >= e.fromElement.clientHeight
		) {
		console.log( "Out!" );
			me.rootDiv.remove();
		}
	
		// フィエクだ
	}
	
	root.hover( me.show, me.hide );
};

function getURI() {
	var uri = location.hostname;
	if (uri == null || typeof uri == "undefined" || uri == "" || uri == "localhost")
		return '*';
	return "http://" + location.hostname;
}

function sendMessageData(e, dataHandler) {
	// window.alert("commontool.js.sendMessageData() : e.origin = " + e.origin);
	if (e.orgin && e.origin != getURI())
		window.alert("あんた谁？");
	else {
		// window.alert("commontool.js.sendMessageData() : pass e.data to dataHandler");
		dataHandler(e.data);
	}
}

function postMessageToParent( gameObjectName, functionName, callbackFuncName, argsStr ) {
	var target = parent.postMessage ? parent : (parent.document.postMessage ? parent.document : undefined);
	if (typeof target != "undefined") {
		// window.alert("commontools.js.postMessageToParent() detect target : " + getURI());
		var hash = {
			str: gameObjectName + "," + functionName + "," + callbackFuncName + "," + argsStr,
		};
		var str = JSON.stringify( hash );
		target.postMessage( str, getURI() );
	}
	else
		window.alert("failed to send message to parent.");
}

function postMessageToParentDirect( gameObjectName, funcName, sendString ) {
	var target = parent.postMessage ? parent : (parent.document.postMessage ? parent.document : undefined);
	if (typeof target != "undefined") {
		var hash = {
			directly: 1,
			objectName: gameObjectName,
			funcName: funcName,
			str: sendString
		};
		var str = JSON.stringify( hash );
		target.postMessage( str, getURI() );
	}
	else
		window.alert("failed to send message to parent.");
}

function getUnityArgsFromListenerData(e) {
	var strArray = e.split(",");
	var gameObjectName = strArray[0];
	var funcName = strArray[1];
	var args = strArray.slice(2).join(",");	
	return {"gameObjectName": gameObjectName, "funcName":funcName, "args":args};
}

function GetUnity() {
	if ( "unityPlayerObject" in window ) {
		return window.unityPlayerObject.getUnity();
	}
	if (typeof unityObject != "undefined") {
		return unityObject.getObjectById("unityPlayer");
	}
	return null;
}

function getUnityGameObjectName( type ) {
	var hash = {
		"bbs"     : "__HTMLBbsMediatorObject__",
		"strategy": "__HTMLStrategyMediatorObject__",
		"strategymatch": "__HTMLStrategyMatchMediatorObject__",
		"siege"   : "__HTMLSiegeMediatorObject__",
		"onikuzi" : "__HTMLOnikuziMediatorObject__",
		"reward"  : "__HTMLRewardMediatorObject__",
		"booster" : "__HTMLBoosterMediatorObject__",
		"treasure": "__HTMLTreasureMediatorObject__",
		"mail"    : "__HTMLMailMediatorObject__",
		"mailbox" : "__HTMLMailBoxMediatorObject__",
	};
	if ( type in hash )
		return hash[ type ];
	return "__HTMLRankingMediatorObject__";
}

function createDateStr( hash, termStr ) {
	if (hash["isValidateTime"] == 0)
		return "表示出来る情报がありません";
	var year 			= hash["year"];
	var month 		= hash["month"];
	var day 			= hash["day"];
	var hour 			= hash["hour"];
	var minute 		= hash["minute"];
	var timeStr 		= termStr + year + "年" + month + "月" + day + "日 " + hour + ":" + ("00" + minute).slice(-2);
	return timeStr;
}

function getRankOrderImageName( order ) {
	if (order == 1)
		return "img/rank_1st.png";
	if (order == 2)
		return "img/rank_2nd.png";
	if (order == 3)
		return "img/rank_3rd.png";
	return null;
}

function getAttribImageName( typeName ) {
	if (typeName == "human")
		return "img/rank_icon_human.png";
	if (typeName == "oni")
		return "img/rank_icon_oni.png";
	return "img/rank_icon_evil.png";
}

function addRankNumberToTag( imageName, rank ) {
	// window.alert( "imageName = "  + imageName + " : rank = " + rank );
	if ( imageName != null )
		return "<img src=" + imageName + ">";
	
	// ランクの桁によってstyleを使い分け
	var digit = (""+rank).length;
	var order_css = "ranking_normal_order_number";
	var unit_css = "ranking_normal_order_number_unit";
	if ( digit >= 7 ) {
		order_css += "7";
		unit_css += "7";
	}
	else if ( digit >= 3 ) {
		order_css += digit;
		unit_css += digit;
	}

	// window.alert( "rank = " + rank + " : digit = " + digit );	
	
	var rankTag = "<B class=" + order_css + ">"
								 + rank
								 + "</B>"
								 + "<B class='ranking_normal_order_number_space'> </B>"
								 + "<B class=" + unit_css + ">位</B>";
	return rankTag;
}

function commonPlaySound( unityName, se ) {
	postMessageToParent( unityName, "playSound", "dummy", se );
}
