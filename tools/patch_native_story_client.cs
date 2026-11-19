// Run via PowerShell Add-Type with the locally supplied Mono.Cecil dependency.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class PatchNativeStoryClient
{
    private static ModuleDefinition target;
    private static Dictionary<string, TypeDefinition> types;
    private static IEnumerable<TypeDefinition> All(TypeDefinition t)
    {
        yield return t;
        foreach (var child in t.NestedTypes)
            foreach (var nested in All(child)) yield return nested;
    }
    private static TypeReference Type(TypeReference source)
    {
        if (source == null || source is GenericParameter) return source;
        if (source is ByReferenceType) return new ByReferenceType(Type(((ByReferenceType)source).ElementType));
        if (source is ArrayType) return new ArrayType(Type(((ArrayType)source).ElementType), ((ArrayType)source).Rank);
        if (source is GenericInstanceType)
        {
            var generic = (GenericInstanceType)source;
            var result = new GenericInstanceType(Type(generic.ElementType));
            foreach (var arg in generic.GenericArguments) result.GenericArguments.Add(Type(arg));
            return result;
        }
        TypeDefinition definition;
        if (types.TryGetValue(source.FullName, out definition)) return definition;
        if (source.Scope is AssemblyNameReference && source.Scope.Name == "mscorlib")
            return new TypeReference(source.Namespace, source.Name, target, target.TypeSystem.CoreLibrary, source.IsValueType);
        return target.ImportReference(source);
    }
    private static MethodReference Method(MethodReference source)
    {
        if (source is GenericInstanceMethod)
        {
            var old = (GenericInstanceMethod)source;
            var result = new GenericInstanceMethod(Method(old.ElementMethod));
            foreach (var arg in old.GenericArguments) result.GenericArguments.Add(Type(arg));
            return result;
        }
        TypeDefinition local;
        if (types.TryGetValue(source.DeclaringType.FullName, out local))
        {
            var found = local.Methods.SingleOrDefault(m => m.Name == source.Name &&
                m.GenericParameters.Count == source.GenericParameters.Count &&
                m.Parameters.Select(p => p.ParameterType.FullName).SequenceEqual(source.Parameters.Select(p => p.ParameterType.FullName)));
            if (found == null) throw new InvalidDataException("Cannot bind " + source.FullName);
            return found;
        }
        var mapped = new MethodReference(source.Name, Type(source.ReturnType), Type(source.DeclaringType));
        mapped.HasThis = source.HasThis;
        mapped.ExplicitThis = source.ExplicitThis;
        mapped.CallingConvention = source.CallingConvention;
        foreach (var generic in source.GenericParameters) mapped.GenericParameters.Add(new GenericParameter(generic.Name, mapped));
        foreach (var parameter in source.Parameters) mapped.Parameters.Add(new ParameterDefinition(Type(parameter.ParameterType)));
        return mapped;
    }
    private static FieldReference Field(FieldReference source)
    {
        TypeDefinition local;
        if (types.TryGetValue(source.DeclaringType.FullName, out local)) return local.Fields.Single(f => f.Name == source.Name);
        return new FieldReference(source.Name, Type(source.FieldType), Type(source.DeclaringType));
    }
    private static MethodDefinition Get(string type, string name)
    {
        var found = types[type].Methods.Where(m => m.Name == name).ToArray();
        if (found.Length != 1) throw new InvalidDataException("Expected one " + type + "." + name + "; found " + found.Length);
        return found[0];
    }
    private static void ReplaceLoadWithConstant(MethodDefinition method, int offset, OpCode expected, OpCode replacement)
    {
        var instruction = method.Body.Instructions.Single(i => i.Offset == offset);
        if (instruction.OpCode != expected) throw new InvalidDataException("Unexpected preview location in " + method.FullName);
        instruction.OpCode = replacement;
        instruction.Operand = null;
    }

    private static void EnableChapterPreview()
    {
        // Keep the completion indicators backed by the save. Change only the
        // selector's prerequisite checks and the tutorial's previous-page limit.
        ReplaceLoadWithConstant(Get("QuestStorySelector", "setQuestId"), 0x02a4, OpCodes.Ldloc_S, OpCodes.Ldc_I4_1);
        ReplaceLoadWithConstant(Get("QuestStorySelector", "setStoryNextButtonSetting"), 0x015c, OpCodes.Ldc_I4_1, OpCodes.Ldc_I4_0);
        ReplaceLoadWithConstant(Get("QuestStoryAreaSelector", "setup"), 0x039e, OpCodes.Ldloc_S, OpCodes.Ldc_I4_1);
        var setup = Get("QuestHUDController", "setup");
        var il = setup.Body.GetILProcessor();
        var done = setup.Body.Instructions.Single(i => i.OpCode == OpCodes.Ret);
        il.InsertBefore(done, il.Create(OpCodes.Ldarg_0));
        il.InsertBefore(done, il.Create(OpCodes.Call, Get("OniNativeStory", "DisablePreviewActions")));
    }

    public static string Run(string original, string helper, string output, int qaPort, bool chapterPreview)
    {
        if (File.Exists(output)) throw new IOException("Refusing to overwrite output");
        byte[] blob = File.ReadAllBytes(original);
        string sha;
        using (var hash = SHA256.Create()) sha = BitConverter.ToString(hash.ComputeHash(blob)).Replace("-", "").ToLowerInvariant();
        if (sha != "0c34100effc18c976850ba66b42660366b0fc2e6cb718abc77204b95b4a512e1")
            throw new InvalidDataException("Unknown PC assembly fingerprint");
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(original));
        resolver.AddSearchDirectory(Path.GetDirectoryName(helper));
        var assembly = AssemblyDefinition.ReadAssembly(new MemoryStream(blob), new ReaderParameters { AssemblyResolver = resolver });
        target = assembly.MainModule;
        if (assembly.Name.HasPublicKey) throw new InvalidDataException("Signed assembly is unsupported");
        var addition = AssemblyDefinition.ReadAssembly(helper, new ReaderParameters { AssemblyResolver = resolver });
        var inserted = addition.MainModule.Types.Where(t => t.Name != "<Module>").ToArray();
        // Cecil metadata is lazy; materialize while each definition still owns its source module.
        foreach (var t in inserted.SelectMany(All))
        {
            foreach (var f in t.Fields) { var force = f.FieldType.FullName; if (f.HasConstant) { var value = f.Constant; } }
            foreach (var m in t.Methods)
            {
                var signature = m.FullName;
                if (m.HasBody) { var force = m.Body.Instructions.ToArray(); }
            }
        }
        foreach (var t in inserted) { addition.MainModule.Types.Remove(t); target.Types.Add(t); }
        // Definitions retain Cecil's original owner field even after collection moves.
        var owner = typeof(TypeReference).GetField("module", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        if (owner == null) throw new InvalidDataException("Unsupported Cecil ownership layout");
        foreach (var t in inserted.SelectMany(All)) owner.SetValue(t, target);
        types = target.Types.SelectMany(All).ToDictionary(t => t.FullName);
        foreach (var t in inserted.SelectMany(All))
        {
            t.BaseType = Type(t.BaseType);
            foreach (var f in t.Fields) f.FieldType = Type(f.FieldType);
            foreach (var m in t.Methods)
            {
                m.ReturnType = Type(m.ReturnType);
                foreach (var p in m.Parameters) p.ParameterType = Type(p.ParameterType);
                if (!m.HasBody) continue;
                foreach (var v in m.Body.Variables) v.VariableType = Type(v.VariableType);
                foreach (var e in m.Body.ExceptionHandlers) if (e.CatchType != null) e.CatchType = Type(e.CatchType);
                foreach (var i in m.Body.Instructions)
                {
                    if (i.Operand is MethodReference) i.Operand = Method((MethodReference)i.Operand);
                    else if (i.Operand is FieldReference) i.Operand = Field((FieldReference)i.Operand);
                    else if (i.Operand is TypeReference) i.Operand = Type((TypeReference)i.Operand);
                }
            }
        }
        if (qaPort < 1024 || qaPort > 65535) throw new InvalidDataException("A loopback test port is required");
        foreach (var name in new[] {"get_ServerBase", "get_DownloadsBase"})
        {
            var get = Get("Configs", name);
            get.Body.Instructions.Clear();
            get.Body.ExceptionHandlers.Clear();
            get.Body.Variables.Clear();
            var writer = get.Body.GetILProcessor();
            writer.Emit(OpCodes.Ldstr, "127.0.0.1:" + qaPort);
            writer.Emit(OpCodes.Ret);
        }
        var api = Get("WebApiClient", "executeQuest");
        var anchor = api.Body.Instructions.Single(i => (i.Operand as string) == "quest/executeQuestEx").Previous;
        if (anchor.OpCode != OpCodes.Ldarg_0 || api.Body.Variables[0].VariableType.FullName != "System.Collections.Hashtable")
            throw new InvalidDataException("Unexpected exploration RPC");
        var rpc = api.Body.GetILProcessor();
        rpc.InsertBefore(anchor, rpc.Create(OpCodes.Ldloc_0));
        rpc.InsertBefore(anchor, rpc.Create(OpCodes.Call, Get("OniNativeStory", "Annotate")));

        var bind = Get("QuestScriptCommand", "bindFunctions");
        var bindIl = bind.Body.GetILProcessor();
        var existing = bind.Body.Instructions.Single(i => (i.Operand as string) == "quest_getLastEventId");
        var delegateCtor = existing.Next.Next.Next;
        var bindCall = delegateCtor.Next;
        var addCall = bindCall.Next;
        var list = existing.Previous.Previous.Operand as FieldReference;
        if (list == null || delegateCtor.OpCode != OpCodes.Newobj || bindCall.OpCode != OpCodes.Callvirt ||
            addCall.OpCode != OpCodes.Callvirt || existing.Previous.OpCode != OpCodes.Ldloc_0)
            throw new InvalidDataException("Unexpected quest function binding");
        var most = bind.Body.Instructions.Last(i => i.OpCode == OpCodes.Ret);
        var accessors = new Dictionary<string, string> { { "quest_localCurrentStep", "CurrentStep" } };
        if (chapterPreview) accessors.Add("quest_previewDialogueChapter", "PreviewDialogueChapter");
        foreach (var accessor in accessors)
        {
            var instructions = new [] {
                bindIl.Create(OpCodes.Ldarg_0), bindIl.Create(OpCodes.Ldfld, list),
                bindIl.Create(OpCodes.Ldloc_0), bindIl.Create(OpCodes.Ldstr, accessor.Key),
                bindIl.Create(OpCodes.Ldnull), bindIl.Create(OpCodes.Ldftn, Get("OniNativeStory", accessor.Value)),
                bindIl.Create(OpCodes.Newobj, (MethodReference)delegateCtor.Operand),
                bindIl.Create(OpCodes.Callvirt, (MethodReference)bindCall.Operand),
                bindIl.Create(OpCodes.Callvirt, (MethodReference)addCall.Operand)
            };
            foreach (var i in instructions) bindIl.InsertBefore(most, i);
        }
        if (chapterPreview) EnableChapterPreview();
        target.AssemblyReferences.Where(r => r.Name == addition.Name.Name).ToList()
            .ForEach(r => target.AssemblyReferences.Remove(r));
        assembly.Write(output);
        return "PC fixture URL, stable native intent and bounded quest step accessor patched";
    }
}
