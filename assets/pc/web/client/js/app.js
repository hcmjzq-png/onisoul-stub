var curFrameName_ = null;
jQuery(document).ready(function($) {
	$(".content").css( "position", "relative" );
	// registerListener("message", sendMessageHandler);

	var reg = new ListenerRegister();
	reg.register( "message", sendMessageHandler );
});

function sendMessageHandler(e) {
	// window.alert("app.js.sendMessageHandler()");
	sendMessageData(e, sendMessage);
}

function sendMessage(e) {
	// window.alert("app.js.sendMessage()");
	var unity = GetUnity();

	var psHash;
	try {
		psHash = JSON.parse( e.data ? e.data : e );
	} catch( e ) {
		return;
	}

	if ( psHash.directly && psHash.directly == 1 ) {
		unity.SendMessage( psHash.objectName, psHash.funcName, psHash.str );
	} else {
		var args = getUnityArgsFromListenerData(psHash.str);
		unity.SendMessage(args.gameObjectName, args.funcName, args.args);

		if (args.funcName == "closeFrame") {
			// window.alert( "app.js.sendMessage().closeFrame" );
			closeFrame();
		}
	}
}

function startBbs( json ) {
	var hash = JSON.parse( json );
	// window.alert("startBbs");
	if (hash.type == "bbs") {
		// window.alert("Weakup Bbs");
		if ( hash.test == 1 )
			$(".content").append("<iframe id='bbs_frame' src='bbs/bbs_test.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		else
			$(".content").append("<iframe id='bbs_frame' src='bbs/bbs.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "bbs_frame";
		unityProxy.begin();
	}
}

function startStrategyMatch( type ) {
	// window.alert("startStrategyMatch");
	if (type == "strategyMatch") {
		// window.alert("Weakup Strategy");
		$(".content").append("<iframe id='strategyMatch_frame' src='strategy/strategymatch.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "strategyMatch_frame";
		unityProxy.begin();
	}
}

function startStrategy( type ) {
	// window.alert("startStrategy");
	if (type == "strategy") {
		// window.alert("Weakup Strategy");
		$(".content").append("<iframe id='strategy_frame' src='strategy/strategy.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "strategy_frame";
		unityProxy.begin();
	}
}

function startSiege( type ) {
	// window.alert("startSiege");
	if (type == "siege") {
		// window.alert("Weakup Siege");
		$(".content").append("<iframe id='siege_frame' src='siege/siege.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "siege_frame";
		unityProxy.begin();
	}
}

function startTitle( type ) {
	// window.alert("startTitle");
	if (type == "title") {
		// window.alert("Weakup Title");
		$(".content").append("<iframe id='title_frame' src='http://www.gwzol.com/?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "title_frame";
		unityProxy.begin();
	}
}

function startMailBox( type ) {
	// window.alert("startTreasure");
	if (type == "mailbox") {
		// window.alert("Weakup Treasure");
		$(".content").append("<iframe id='mailbox_frame' src='mailbox/mailbox.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e;margin:0'>");
		curFrameName_ = "mailbox_frame";
		unityProxy.begin();
	}
}

function startMail( type ) {
	// window.alert("startTreasure");
	if (type == "mail") {
		// window.alert("Weakup Treasure");
		$(".content").append("<iframe id='mail_frame' src='mail/mail.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "mail_frame";
		unityProxy.begin();
	}
}

function startTreasure( type ) {
	// window.alert("startTreasure");
	if (type == "treasure") {
		// window.alert("Weakup Treasure");
		$(".content").append("<iframe id='treasure_frame' src='treasure/treasure.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "treasure_frame";
		unityProxy.begin();
	}
}

function startBooster( type ) {
	// window.alert("startBooster");
	if (type == "booster") {
		// window.alert("Weakup Booster");
		$(".content").append("<iframe id='booster_frame' src='booster/booster.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "booster_frame";
		unityProxy.begin();
	}
}

function startOnikuzi( type ) {
	// window.alert("startOnikuzi");
	if (type == "onikuzi") {
		// window.alert("Weakup Onikuzi");
		$(".content").append("<iframe id='onikuzi_frame' src='onikuzi/onikuzi.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "onikuzi_frame";
		unityProxy.begin();
	}
}

function startReward( type ) {
    //    	 window.alert("startReward");
	if (type == "reward") {
		// window.alert("Weakup Reward");
		$(".content").append("<iframe id='reward_frame' src='reward/reward.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "reward_frame";
		unityProxy.begin();
	}
}

function startRanking( type ) {
    //	 window.alert( type );
	if (type == "score") {
		// window.alert("Score");
		$(".content").append("<iframe id='ranking_frame' src='ranking/ranking_score.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "ranking_frame";
		unityProxy.begin();
	} else if (type == "tenka") {
		// window.alert("Tenka");
		$(".content").append("<iframe id='ranking_frame' src='ranking/ranking_tenka.html?revision=" + ONI_SOUL_REVISION + "' frameborder = 0 style='background-color:#2e2e2e'>");
		curFrameName_ = "ranking_frame";
		unityProxy.begin();
	}
}

function reseiveMessage(str) {
	if (curFrameName_ != null) {
		// window.alert("app.reseiveMessage()");
		document.getElementById(curFrameName_).contentWindow.postMessage(str, getURI());
	}
}

function closeFrame(str) {
	unityProxy.end();
	// window.alert( "app.js.closeFrame(): " + curFrameName_ );
	var frame = $("#" + curFrameName_);
	frame.remove();
	curFrameName_ = null;
}

function alertWindow(str) {
	window.alert( str );
}


function openURL( url ) {
	try {
            if ( 0 == url.indexOf( "http" ) && main.getContainer() != 'mixi' ) {
			window.open( url );
		} else {
			var target = parent.postMessage ? parent : (parent.document.postMessage ? parent.document : undefined);
			if (typeof target != 'undefined') {
	    		target.postMessage( url , "*");
			}
		}
    } catch (e) {
		alert( e );
    }
}

/** yahoo mobage */
function onMessageToParent(message) {
    try {
	var target = parent.postMessage ? parent : (parent.document.postMessage ? parent.document : undefined);
	if (typeof target != 'undefined') {
	    target.postMessage(message, "*");
	}
    } catch( e ) {
	alert( e );
    };
}
