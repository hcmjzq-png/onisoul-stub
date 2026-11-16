// Injected into the fingerprinted original PC Assembly-CSharp, never the EXE.
// Keep the original loader/cache path and sprite layout; scope readiness to hover.
using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

public static class OniCountryPreviewFix
{
    public const string Version = "country76-20261116a";
    public const float TimeoutSeconds = 30f;
    private sealed class Pending
    {
        public LoginCharacterIcon Icon;
        public bool Started;
        public bool Failed;
        public float StartedAt;
        public string Title;
    }
    private static readonly Dictionary<int, Pending> pending = new Dictionary<int, Pending>();
    private static LoginCharacterIcon current;
    private static readonly FieldInfo loading = Field("bNowLoading");
    private static readonly FieldInfo loaded = Field("bLoadTexture");
    private static readonly FieldInfo setup = Field("bAlreadySetup");

    private static FieldInfo Field(string name)
    {
        FieldInfo field = typeof(LoginCharacterIcon).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);
        if (field == null) throw new MissingFieldException("LoginCharacterIcon", name);
        return field;
    }
    private static bool Flag(FieldInfo field, LoginCharacterIcon icon) { return (bool)field.GetValue(icon); }
    private static Pending Get(LoginCharacterIcon icon)
    {
        int id = icon.GetInstanceID();
        Pending entry;
        if (!pending.TryGetValue(id, out entry))
        {
            entry = new Pending();
            entry.Icon = icon;
            entry.Title = icon.title_ == null ? "" : icon.title_.Text;
            pending.Add(id, entry);
        }
        return entry;
    }
    public static void Activate(LoginCharacterIcon icon)
    {
        current = icon;
        Pending entry = Get(icon);
        if (entry.Failed)
        {
            entry.Failed = false;
            entry.Started = false;
            if (icon.title_ != null) icon.title_.Text = entry.Title;
            Indicator(icon, true);
        }
    }
    public static void Deactivate(LoginCharacterIcon icon)
    {
        if (current == icon) current = null;
        // The original global async loader can finish while this preview is hidden.
    }
    public static void Release(LoginCharacterIcon icon)
    {
        Deactivate(icon);
        pending.Remove(icon.GetInstanceID());
    }
    public static bool BeforeUpdate(LoginCharacterIcon icon)
    {
        if (!Flag(setup, icon)) return false;
        Pending entry = Get(icon);
        if (Flag(loaded, icon)) return true;
        if (entry.Failed) return false;
        if (!Flag(loading, icon))
        {
            // OnEnable can precede setup; capture the localized title after setup.
            entry.Title = icon.title_ == null ? "" : icon.title_.Text;
            entry.StartedAt = Time.realtimeSinceStartup;
            entry.Started = true;
            return true;
        }
        if (!entry.Started)
        {
            entry.StartedAt = Time.realtimeSinceStartup;
            entry.Started = true;
        }
        if (Time.realtimeSinceStartup - entry.StartedAt < TimeoutSeconds) return true;
        // clear cancels this sprite's exact callback and clears its same-file shortcut.
        // A later hover may retry; a failed country's state cannot block another one.
        icon.icon_.clear();
        loading.SetValue(icon, false);
        loaded.SetValue(icon, false);
        entry.Failed = true;
        Indicator(icon, false);
        if (icon.title_ != null) icon.title_.Text = "读取失败";
        Debug.LogWarning("OniCountryPreview: bounded load failed; hover again to retry.");
        return false;
    }
    private static void Indicator(LoginCharacterIcon icon, bool visible)
    {
        Transform indicator = icon.transform.FindChild("Indicator");
        if (indicator != null) indicator.gameObject.SetActiveRecursively(visible);
    }
    // Signature intentionally matches the old instance isLocking call's stack.
    public static bool IsLocked(LoginEnvironment unused, string unusedFlag)
    {
        return current == null || current.icon_ == null || !Flag(loaded, current) || !current.icon_.IsValid;
    }
    public static string VersionUrl(string url)
    {
        if (url.StartsWith("http") &&
            (url.IndexOf("/assets/chara/", StringComparison.Ordinal) >= 0 ||
             url.IndexOf("/assets2/chara/", StringComparison.Ordinal) >= 0))
            return url + (url.IndexOf('?') >= 0 ? "&" : "?") + "countryfix=" + Version;
        return url;
    }
}
