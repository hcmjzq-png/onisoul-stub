using System;
using System.Collections;

// Isolated PC fixture only. Lives in the client DLL so automatic HTTP retries
// reuse the same serialized intent without authorizing a fresh step.
public static class OniNativeStory
{
    public static int CurrentStep()
    {
        var p = Singleton<QuestDataCache>.Instance.QuestParameter;
        return p != null && p.getType() == "story" && p.questId_ == 0 &&
            p.chapterId_ == 1 && p.areaId_ == 1 ? p.step_ : int.MaxValue;
    }

    public static void Annotate(Hashtable request)
    {
        request["expectedStep"] = CurrentStep();
        request["operationId"] = Guid.NewGuid().ToString("N");
    }

    public static int PreviewDialogueChapter()
    {
        var p = Singleton<QuestDataCache>.Instance.QuestParameter;
        return p != null && p.getType() == "story" ? p.questId_ * 10 + p.chapterId_ : -1;
    }

    public static void DisablePreviewActions(QuestHUDController hud)
    {
        hud.questButton_.gameObject.active = false;
        hud.autoSkip_.gameObject.SetActiveRecursively(false);
        hud.fullAutoSkip_.gameObject.SetActiveRecursively(false);
    }
}
