var unityProxy = function() {
	var receiveFunction = [];
	var responseId = 0;
	var unityTarget = "GameObject";
	var frameId = "_frame";
	var width;
	var height;
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
		
		isSupported : function() {
			var name = navigator.userAgent;
			var os   = navigator.platform;
			if ( os.indexOf( "Win" ) > -1 && name.indexOf( "Safari" ) > -1 && name.indexOf( "Chrome" ) < 0 ) {
				return false;
			}
			if ( os.indexOf( "Win" ) > -1 && navigator.appName.indexOf( "Microsoft Internet Explorer" ) > -1 ) {
				return false;
			}
			return true;
		},
		
		getEmbedTag : function() {
			var tag = $("embed");
			if ( tag.size() == 0 ) {
				tag = $("object");
			}
			return tag;
		},
		
		focus : function() {
			var unity = unityProxy.getUnity();
			if( null != unity ) {
		        unity.contentEditable = true;
        		unity.focus();
			}
		},
		
		begin : function() {
			if ( unityProxy.isSupported() ) {
				return;
			}
			try {
				var target = unityProxy.getEmbedTag();
				width = target.css( "width" );
				height= target.css( "height" );
				target.css( "width", "1px" );
				target.css( "height", "1px" );
			} catch( e ) {
			}
		},
		
		end : function() {
			if ( unityProxy.isSupported() ) {
				return;
			}
			try {
				var target = unityProxy.getEmbedTag();
				target.css( "width", width );
				target.css( "height", height );
				unityProxy.focus();
			} catch( e ) {
			}
		},
		
		open : function( targetName, src, id ) {
			try {
				unityTarget = targetName;
				frameId = id;
				var link = "<iframe id='" + frameId + "' frameborder=0 src=" + "'" + src + "?revision=" + ONI_SOUL_REVISION + "'>";
				$(".content").append( link );
				unityProxy.begin();
			} catch( e ) {
				alert( e );
			}
		},

		close : function() {
			try {
				var frame = $( "#" + frameId );
				unityProxy.send( "onEnd", null, null );
				frame.remove();
			} catch( e ) {
				alert( e );
			} finally {
				unityProxy.end();
			}
		},

		playSe : function( id ) {
			var param = { id : id };
			unityProxy.send( "playSe", param, null );
		},


		receive : function( param ) {
			var res = null;
			try {
				res = JSON.parse( param );
				if ( res.responseId in receiveFunction ) {
					var callback = receiveFunction[ res.responseId ];
					delete receiveFunction[ res.responseId ];
					delete res[ "responseId" ];
					if ( null != callback ) {
						callback( res );
					}
				}
			} catch( e ) {
				alert( e );
			}
		},

		send : function( functionName, argv, callback ) {
			if ( argv == null ) {
				argv = {};
			}

			var responseKey = String( responseId++ );
			receiveFunction[ responseKey ] = callback;
			
			var param = {
				"receive" : "unityProxy.receive",
				"argv"     : argv,
				"function" : functionName,
				"responseId": responseKey,
			};
			var str = JSON.stringify( param );
			main.getUnity().SendMessage( unityTarget, "receive", str );
		},

	};
}();

