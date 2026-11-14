var social = function() {
	return {
		tweet : function( argv ) {
		},

		netcafe : function( argv ) {
			var w = 500; var h = 300;
			var l = 0; var t = 0;
			var param = JSON.parse( argv );
			var url = param[ "url" ]
					+ "?gameID="  + encodeURI( param["gameId"] )
					+ "&userID=" + encodeURI( param["userId"] )
					+ "&tStamp=" + encodeURI( param["time"] )
					+ "&hash=" + encodeURI( param["hash"] );
			if ( main.getContainer() == 'mixi' ) {
			    openURL( url );
			}
			else {
			    window.open(url, "", "width="+w+",height="+h+",left="+l+",top="+t+",scrollbars=yes,resizable=yes,toolbar=no,location=no");
			}
		},


	};

}();
