// Runs the injected policy without a Unity process; native/UI QA is separate.
using System;
namespace UnityEngine
{
    public class Object { private static int next; private int id=++next; public int GetInstanceID(){return id;} }
    public class Component : Object { public Transform transform=new Transform(); }
    public class Transform { public GameObject gameObject=new GameObject(); public Transform FindChild(string s){return null;} }
    public class GameObject { public void SetActiveRecursively(bool b){} }
    public static class Time { public static float realtimeSinceStartup; }
    public static class Debug { public static void LogWarning(object o){} }
}
public class SpriteText { public string Text="initial"; }
public class AsyncLoadSprite
{
    public bool IsValid; public int Cleared;
    public void clear(){Cleared++;} // The old sprite clear does NOT reset IsValid.
}
public class LoginEnvironment {}
public class LoginCharacterIcon : UnityEngine.Component
{
    private bool bNowLoading;
    private bool bLoadTexture;
    private bool bAlreadySetup=true;
    public AsyncLoadSprite icon_=new AsyncLoadSprite();
    public SpriteText title_=new SpriteText();
    public void State(bool loading,bool loaded){bNowLoading=loading;bLoadTexture=loaded;icon_.IsValid=loaded;}
    public bool Loading {get{return bNowLoading;}}
    public bool Ready {get{return bLoadTexture;}}
}
public static class CountryFixHarness
{
    static void Assert(bool pass,string name){if(!pass)throw new Exception(name);Console.WriteLine("PASS "+name);}
    public static void Main()
    {
        var missing=new LoginCharacterIcon();var ready=new LoginCharacterIcon();
        missing.State(true,false);ready.State(false,true);
        OniCountryPreviewFix.Activate(missing);
        Assert(OniCountryPreviewFix.IsLocked(null,"BushoTrans"),"unloaded current country blocks its own click");
        OniCountryPreviewFix.Activate(ready);
        Assert(!OniCountryPreviewFix.IsLocked(null,"BushoTrans"),"other country's pending download cannot block a ready country");
        OniCountryPreviewFix.Activate(missing);
        OniCountryPreviewFix.Deactivate(ready);
        Assert(OniCountryPreviewFix.IsLocked(null,"BushoTrans"),"late hidden-country completion does not unlock current country");
        UnityEngine.Time.realtimeSinceStartup=0;OniCountryPreviewFix.BeforeUpdate(missing);
        UnityEngine.Time.realtimeSinceStartup=31;
        Assert(!OniCountryPreviewFix.BeforeUpdate(missing)&&!missing.Loading&&!missing.Ready&&missing.icon_.Cleared==1,"deadline cancels exactly this preview and clears loading state");
        Assert(!OniCountryPreviewFix.BeforeUpdate(missing)&&missing.icon_.Cleared==1,"failed preview does not retry every frame");
        OniCountryPreviewFix.Deactivate(missing);OniCountryPreviewFix.Activate(missing);
        Assert(OniCountryPreviewFix.BeforeUpdate(missing),"hover again permits retry after a failure");
        OniCountryPreviewFix.Activate(ready);OniCountryPreviewFix.BeforeUpdate(ready);
        Assert(ready.icon_.Cleared==0&&!OniCountryPreviewFix.IsLocked(null,"BushoTrans"),"ready memory image is preserved on revisit");
        OniCountryPreviewFix.Release(ready);
        Assert(OniCountryPreviewFix.IsLocked(null,"BushoTrans"),"destroyed preview is not selectable");
        Assert(OniCountryPreviewFix.VersionUrl("http://host/client/pc/jp/assets/chara/hash.unity3d?r=1").IndexOf("countryfix=")>0,"country bundle requests bypass obsolete Qt entries");
        Assert(OniCountryPreviewFix.VersionUrl("http://host/client/pc/jp/assets/scene/login.unity3d?r=1")=="http://host/client/pc/jp/assets/scene/login.unity3d?r=1","unrelated scene URLs preserve their original cache key");
    }
}
