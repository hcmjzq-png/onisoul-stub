// Run against the patched app's extracted managed assemblies on .NET Framework.
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.Serialization;

public static class ClientActionPointHarness
{
    private const BindingFlags Fields = BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;

    public static void Main()
    {
        var clock = Uninitialized<ClockTimer>();
        typeof(ServiceLocator<ClockTimer>).GetField("refTarget_", Fields).SetValue(null, new WeakReference(clock));
        typeof(ServiceLocator<ClockTimer>).GetField("isInitialized_g", Fields).SetValue(null, true);
        foreach (string key in new[] { "politicPoint", "missionPoint", "battlePoint" })
            Exercise(key, clock);
        Console.WriteLine("three point timers: snapshot phase, next tick, delayed update, cap and legacy fallback passed");
    }

    private static void Exercise(string key, ClockTimer clock)
    {
        var point = new UserStatus.ActionPoint { point_ = 10, maxPoint_ = 100, confirmTime_ = 1000 };
        var user = Uninitialized<UserStatus>();
        Set(user, "actionPoints_", new Dictionary<string, UserStatus.ActionPoint> { { key, point } });
        var timer = NewTimer(user, key);

        Set(clock, "absoluteTime_", 1025.25);
        timer.setActionPoint(1025, point.point_);
        Expect(timer.Sec == 95, key + " snapshot phase");
        Set(clock, "absoluteTime_", 1119.75);
        timer.update();
        Expect(timer.Sec == 1 && point.point_ == 10, key + " before next tick");
        Set(clock, "absoluteTime_", 1120.0);
        timer.update();
        Expect(timer.Sec == 120 && point.point_ == 11, key + " exact next tick");

        Set(clock, "absoluteTime_", 1370.0);
        timer.update();
        Expect(timer.Sec == 110 && point.point_ == 13, key + " two delayed ticks retain phase");
        point.point_ = 17;
        point.confirmTime_ = 1362;
        timer.setActionPoint(1370, point.point_);
        Expect(timer.Sec == 112, key + " later snapshot replaces local phase");

        point.maxPoint_ = 18;
        Set(clock, "absoluteTime_", 1700.0);
        timer.update();
        Expect(timer.Sec == 0 && point.point_ == 18, key + " cap after delayed update");
        timer.update();
        point.point_ = 17;
        Expect(timer.Sec == 120, key + " timer from full");

        point.point_ = 10.5;
        point.confirmTime_ = 0;
        timer = NewTimer(user, key);
        timer.setActionPoint(1700, point.point_);
        Expect(timer.Sec == 60, key + " legacy fraction fallback");
    }

    private static ActionPointRefresher NewTimer(UserStatus user, string key)
    {
        var timer = Uninitialized<ActionPointRefresher>();
        Set(timer, "userStatus_", user);
        Set(timer, "key_", key);
        Set(timer, "recoverIntervalTime_", 120);
        Set(timer, "refreshTime_", -1.0);
        return timer;
    }

    private static T Uninitialized<T>()
    {
        return (T)FormatterServices.GetUninitializedObject(typeof(T));
    }

    private static void Set(object instance, string name, object value)
    {
        instance.GetType().GetField(name, Fields).SetValue(instance, value);
    }

    private static void Expect(bool condition, string reason)
    {
        if (!condition) throw new Exception(reason);
    }
}
