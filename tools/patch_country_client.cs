// Run via PowerShell Add-Type with the locally supplied Mono.Cecil dependency.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class PatchCountryClient
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
    private static void AddEvent(string name, MethodReference callback)
    {
        var icon = types["LoginCharacterIcon"];
        if (icon.Methods.Any(m => m.Name == name)) throw new InvalidDataException("Unexpected existing " + name);
        var method = new MethodDefinition(name, MethodAttributes.Private | MethodAttributes.HideBySig, target.TypeSystem.Void);
        icon.Methods.Add(method);
        var il = method.Body.GetILProcessor();
        il.Append(il.Create(OpCodes.Ldarg_0)); il.Append(il.Create(OpCodes.Call, callback)); il.Append(il.Create(OpCodes.Ret));
    }
    public static string Run(string original, string helper, string output)
    {
        if (File.Exists(output)) throw new IOException("Refusing to overwrite output");
        byte[] blob = File.ReadAllBytes(original);
        string sha;
        using (var hash = SHA256.Create()) sha = BitConverter.ToString(hash.ComputeHash(blob)).Replace("-", "").ToLowerInvariant();
        if (sha != "b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e")
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
        var fix = "OniCountryPreviewFix";
        AddEvent("OnEnable", Get(fix, "Activate"));
        AddEvent("OnDisable", Get(fix, "Deactivate"));
        AddEvent("OnDestroy", Get(fix, "Release"));
        var update = Get("LoginCharacterIcon", "Update");
        var processor = update.Body.GetILProcessor();
        var first = update.Body.Instructions[0];
        processor.InsertBefore(first, processor.Create(OpCodes.Ldarg_0));
        processor.InsertBefore(first, processor.Create(OpCodes.Call, Get(fix, "BeforeUpdate")));
        processor.InsertBefore(first, processor.Create(OpCodes.Brtrue, first));
        processor.InsertBefore(first, processor.Create(OpCodes.Ret));
        int lockCalls = 0;
        foreach (var t in All(types["LoginCharacterIcon"]))
            foreach (var m in t.Methods.Where(m => m.HasBody))
                foreach (var i in m.Body.Instructions.ToArray())
                {
                    var call = i.Operand as MethodReference;
                    if (call != null && call.DeclaringType.Name == "LoginEnvironment" &&
                        (call.Name == "lockFlag" || call.Name == "unlockFlag"))
                    {
                        i.OpCode = OpCodes.Pop; i.Operand = null;
                        m.Body.GetILProcessor().InsertAfter(i, Instruction.Create(OpCodes.Pop));
                        lockCalls++;
                    }
                }
        if (lockCalls != 2) throw new InvalidDataException("Expected exactly two icon lock calls");
        var gate = Get("LoginColorMask", "checkRegion").Body.Instructions.Where(i =>
            i.Operand is MethodReference && ((MethodReference)i.Operand).Name == "isLocking").ToArray();
        if (gate.Length != 1) throw new InvalidDataException("Unexpected country click gate");
        gate[0].OpCode = OpCodes.Call; gate[0].Operand = Get(fix, "IsLocked");
        var url = Get("Loader", "getHashFilePath");
        var returns = url.Body.Instructions.Where(i => i.OpCode == OpCodes.Ret).ToArray();
        if (returns.Length != 1) throw new InvalidDataException("Unexpected URL control flow");
        url.Body.GetILProcessor().InsertBefore(returns[0], Instruction.Create(OpCodes.Call, Get(fix, "VersionUrl")));
        target.AssemblyReferences.Where(r => r.Name == addition.Name.Name).ToList().ForEach(r => target.AssemblyReferences.Remove(r));
        assembly.Write(output);
        return "Patched icon lifecycle, bounded retry state, current-country click gate and chara cache version";
    }
}
