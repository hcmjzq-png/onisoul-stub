// Run with the actual patched DLL and its original managed dependencies.
// Never starts Unity or loads a script; callback/state policy only.
using System;
using System.Reflection;

public class StartupRecoveryHarness
{
    private static int count;
    private static void Finish() { count++; }
    private static FieldInfo Field(string name)
    {
        return typeof(Script.Player).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);
    }
    private static void Assert(bool value, string reason)
    {
        if (!value) throw new Exception(reason);
    }
    public static void Main()
    {
        try { Check(); }
        catch (Exception error)
        {
            Console.WriteLine(error.GetType().FullName);
            if (error.InnerException != null) Console.WriteLine(error.InnerException.GetType().FullName);
            Environment.Exit(1);
        }
    }
    private static void Check()
    {
        var recover = typeof(Script.Player).GetMethod("OniRecoverMissingStartup",
            BindingFlags.Instance | BindingFlags.NonPublic);
        Assert(recover != null, "missing recovery");
        var notify = typeof(Script.Player).GetMethod("OniNotifyStartupFailure",
            BindingFlags.Static | BindingFlags.NonPublic);
        var reset = typeof(Script.Player).GetMethod("OniResetStartupFailure",
            BindingFlags.Static | BindingFlags.NonPublic);
        var failed = typeof(Script.Player).GetMethod("OniIsStartupFailure",
            BindingFlags.Static | BindingFlags.NonPublic);
        Assert(!(bool)failed.Invoke(null, new object[] { "scr2_000001_01" }), "fresh load marked failed");
        notify.Invoke(null, new object[] { "assets/scr/scr1_000001.unity3d" });
        Assert(!(bool)failed.Invoke(null, new object[] { "scr2_000001_01" }), "other file marked startup failed");
        notify.Invoke(null, new object[] { "assets/scr/scr2_000001.unity3d" });
        Assert((bool)failed.Invoke(null, new object[] { "scr2_000001_01" }), "terminal startup failure not propagated");
        Assert(!(bool)failed.Invoke(null, new object[] { "scr1_000001_01" }), "tutorial affected");
        var load = typeof(Script.StanderdLibrary).GetMethod("loadFile", BindingFlags.Static | BindingFlags.NonPublic);
        var waiting = (System.Collections.IEnumerator)load.Invoke(null,
            new object[] { "scr2_000001_01", "scr2_000001_01" });
        Assert(!waiting.MoveNext(), "failed startup file coroutine kept waiting");
        Assert(!waiting.MoveNext(), "ended file coroutine resumed");
        reset.Invoke(null, new object[] { "scr1_000001_01" });
        Assert((bool)failed.Invoke(null, new object[] { "scr2_000001_01" }), "unrelated play cleared failure");
        reset.Invoke(null, new object[] { "scr2_000001_01" });
        Assert(!(bool)failed.Invoke(null, new object[] { "scr2_000001_01" }), "retry did not reset failure");
        foreach (string prefix in new string[] { "scr1_000001_01", "scr2_000003_01", "scr2_000010_01", "", "scr2_000001_02" })
        {
            var other = new Script.Player(null);
            Field("prefix_").SetValue(other, prefix);
            Field("endCallback_").SetValue(other, new Script.Interpreter.Callback(Finish));
            recover.Invoke(other, null);
            Assert(count == 0, "unexpected script bypass: " + prefix);
            Assert(Field("endCallback_").GetValue(other) != null, "consumed other script callback");
        }
        var startup = new Script.Player(null);
        Field("prefix_").SetValue(startup, "scr2_000001_01");
        Field("endCallback_").SetValue(startup, new Script.Interpreter.Callback(Finish));
        recover.Invoke(startup, null);
        Assert(count == 1, "ordinary startup callback not delivered");
        Assert(Field("endCallback_").GetValue(startup) == null, "callback not consumed");
        recover.Invoke(startup, null);
        Assert(count == 1, "callback repeated");
        Console.WriteLine("startup recovery: terminal failure propagation/reset, 5 excluded prefixes, one-shot completion and null callback passed");
    }
}
