var main = function() {
	return {
		getUnity : function() {
			if ( "unityPlayerObject" in window ) {
				return window.unityPlayerObject.getUnity();
			}
			if ( "unityObject" in window ) {
				return window.unityObject.getObjectById("unityPlayer");
			}
			return null;
		},
		
		start : function() {
			var host = main.getHost();
			main.getUnity().SendMessage("bootup", "setHost", host );
		},

		reload : function() {
			if ( !navigator.cookieEnabled ) {
				main.reloadTop();
				return;
  			}
			location.reload();
		},

		reloadTop : function() {
			var urlList = {
				cog: 'http://www.gwzol.com',
				nhn: 'http://oni-soul.hangame.co.jp/',
				msn: 'http://game.games.jp.msn.com/coregame/oni-soul/',
				nico:'http://nico-members.oni-soul.jp/',
				mixi:'http://mixi.jp/',
				ymbga:'http://yahoo-mbga.jp/',
			};
			try {
				var target = location.href;
				var container = main.getContainer();
				if ( container != "" && container in urlList ) {
					target = urlList[ container ];
				}
				location.href = target;
			} catch( e ) {
				alert( e );
			}
		},

		getContainer : function() {
			var target = "";
			var query = main.getQuery();
			if ( "container" in query ) {
				target = query[ "container" ];
			}
			return target;
		},

		getHost : function() {
			return location.href.split( '/' )[ 2 ];
		},

		makeParam : function( idName, tokenName ) {
			var hostName = main.getHost();
			var param = { id : idName, token : tokenName, host : hostName };
			return JSON.stringify( param );
		}, 

		login : function() {
			var query = main.getQuery();
			var qNow = 0;
			var qId = "";
			var qToken = "";
			if ( "token" in query && "now" in query && "id" in query ) {
				qNow = query[ "now" ];
				qId   = query[ "id" ];
				qToken= query[ "token" ];
			} else {
				// 不正クエリー or クエリーが无い
				main.getUnity().SendMessage( "bootup", "slogin", "" );
				return;
			}

			// 不正パラメータ
			var param = $.cookie('param');
			var jsonParam = JSON.parse( param );
			if ( jsonParam == null ) {
				main.getUnity().SendMessage( "bootup", "login", main.makeParam( qId, qToken ) );
				return;
			}
			// ユーザー违い
			if ( qId != jsonParam.id ) {
				$.cookie('param', null );
				main.getUnity().SendMessage( "bootup", "login", main.makeParam( qId, qToken ) );
				return;
			}

			// クエリーの方が最新
			if ( jsonParam.now < qNow ) {
				main.getUnity().SendMessage( "bootup", "login", main.makeParam( qId, qToken ) );
				return;
			}

			// cookie采用
			main.getUnity().SendMessage( "bootup", "slogin", param );
		},

		storeParam : function( param ) {
			if ( !navigator.cookieEnabled ) {
				return;
  			}
			$.cookie('param', param, { expires: 30 } ); 
		},
		
		getQuery : function(){
			var str = location.search;
			var dec = decodeURIComponent;
			var par = new Array, itm;
			if ( typeof( str ) == 'undefined' ) return par;
			if ( str.indexOf( '?', 0 ) > -1) str = str.split( '?' )[ 1 ];
			str = str.split('&');
			for( var i = 0; str.length > i; ++i ) {
				itm = str[ i ].split( "=" );
				if ( itm[ 0 ] != '') {
					par[ itm[ 0 ] ] = typeof( itm[ 1 ] ) == 'undefined' ? true : dec( itm[ 1 ] );
				}
			}
			return par;
		},
	};
}();
