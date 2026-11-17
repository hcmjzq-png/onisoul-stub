// Offline compatibility patch. Missing ordinary startup content stays missing;
// finish only that failed wait through its existing callback and FSM exit.
using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class PatchStartupClient
{
    public const string RecoveryName = "OniRecoverMissingStartup";
    public static string Run(string input, string output, string references)
    {
        if (File.Exists(output)) throw new IOException("Refusing to overwrite output");
        var bytes = File.ReadAllBytes(input);
        string hash;
        using (var sha = SHA256.Create())
            hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        if (hash != "b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e" &&
            hash != "05f8e6963aeee70bde0aa25b56457c0e800d1d655d160db0c4512f6d1a54bb39")
            throw new InvalidDataException("Unknown PC assembly fingerprint");
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(input));
        resolver.AddSearchDirectory(references);
        using (var assembly = AssemblyDefinition.ReadAssembly(new MemoryStream(bytes),
            new ReaderParameters { AssemblyResolver = resolver }))
        {
            if (assembly.Name.HasPublicKey) throw new InvalidDataException("Signed assembly unsupported");
            var module = assembly.MainModule;
            var player = module.Types.Single(t => t.FullName == "Script.Player");
            if (player.Methods.Any(m => m.Name == RecoveryName))
                throw new InvalidDataException("Startup recovery already present");
            var iterator = player.NestedTypes.Single(t => t.Name.StartsWith("<loadAndPlay>"));
            var move = iterator.Methods.Single(m => m.Name == "MoveNext");
            var owner = iterator.Fields.Single(f => f.FieldType.FullName == player.FullName);
            var errorLog = move.Body.Instructions.Single(i => i.Operand is MethodReference &&
                ((MethodReference)i.Operand).FullName == "System.Void UnityEngine.Debug::LogError(System.Object)");
            if (!move.Body.Instructions.Any(i => (i.Operand as string) == "file load error:") ||
                !move.Body.Instructions.Any(i => i.Operand is MethodReference &&
                    ((MethodReference)i.Operand).Name == "get_IsError"))
                throw new InvalidDataException("Unexpected script error branch");
            var prefix = player.Fields.Single(f => f.Name == "prefix_");
            var callback = player.Fields.Single(f => f.Name == "endCallback_");
            var stop = player.Methods.Single(m => m.Name == "stop");
            var equality = player.Methods.Single(m => m.Name == "play").Body.Instructions
                .Select(i => i.Operand as MethodReference).Single(m => m != null && m.Name == "op_Equality");
            var interpreter = module.Types.Single(t => t.FullName == "Script.Interpreter");
            var invoke = interpreter.NestedTypes.Single(t => t.Name == "Callback")
                .Methods.Single(m => m.Name == "Invoke");
            var failed = new FieldDefinition("OniStartupLoadFailed",
                FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Boolean);
            player.Fields.Add(failed);
            var reset = new MethodDefinition("OniResetStartupFailure",
                MethodAttributes.Private | MethodAttributes.Static, module.TypeSystem.Void);
            reset.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
            player.Methods.Add(reset);
            var resetIl = reset.Body.GetILProcessor();
            var resetDone = resetIl.Create(OpCodes.Ret);
            resetIl.Append(resetIl.Create(OpCodes.Ldarg_0));
            resetIl.Append(resetIl.Create(OpCodes.Ldstr, "scr2_000001_01"));
            resetIl.Append(resetIl.Create(OpCodes.Call, equality));
            resetIl.Append(resetIl.Create(OpCodes.Brfalse, resetDone));
            resetIl.Append(resetIl.Create(OpCodes.Ldc_I4_0));
            resetIl.Append(resetIl.Create(OpCodes.Stsfld, failed));
            resetIl.Append(resetDone);
            var notify = new MethodDefinition("OniNotifyStartupFailure",
                MethodAttributes.Assembly | MethodAttributes.Static, module.TypeSystem.Void);
            notify.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
            player.Methods.Add(notify);
            var notifyIl = notify.Body.GetILProcessor();
            var notifyDone = notifyIl.Create(OpCodes.Ret);
            notifyIl.Append(notifyIl.Create(OpCodes.Ldarg_0));
            notifyIl.Append(notifyIl.Create(OpCodes.Ldstr, "assets/scr/scr2_000001.unity3d"));
            notifyIl.Append(notifyIl.Create(OpCodes.Call, equality));
            notifyIl.Append(notifyIl.Create(OpCodes.Brfalse, notifyDone));
            notifyIl.Append(notifyIl.Create(OpCodes.Ldc_I4_1));
            notifyIl.Append(notifyIl.Create(OpCodes.Stsfld, failed));
            notifyIl.Append(notifyDone);
            var isFailed = new MethodDefinition("OniIsStartupFailure",
                MethodAttributes.Assembly | MethodAttributes.Static, module.TypeSystem.Boolean);
            isFailed.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
            player.Methods.Add(isFailed);
            var failedIl = isFailed.Body.GetILProcessor();
            failedIl.Append(failedIl.Create(OpCodes.Ldsfld, failed));
            failedIl.Append(failedIl.Create(OpCodes.Ldarg_0));
            failedIl.Append(failedIl.Create(OpCodes.Ldstr, "scr2_000001_01"));
            failedIl.Append(failedIl.Create(OpCodes.Call, equality));
            failedIl.Append(failedIl.Create(OpCodes.And));
            failedIl.Append(failedIl.Create(OpCodes.Ret));

            var play = player.Methods.Single(m => m.Name == "play");
            var setPrefix = play.Body.Instructions.Single(i =>
                i.OpCode == OpCodes.Stfld && i.Operand == prefix);
            var playIl = play.Body.GetILProcessor();
            var loadName = playIl.Create(OpCodes.Ldarg_1);
            playIl.InsertAfter(setPrefix, loadName);
            playIl.InsertAfter(loadName, playIl.Create(OpCodes.Call, reset));

            // Loader's terminal HTTP failure used to discard every callback.
            // Signal just this ordinary startup bundle after retries are exhausted.
            var loader = module.Types.Single(t => t.FullName == "Loader");
            var process = loader.NestedTypes.Single(t => t.Name.StartsWith("<process>"));
            var processMove = process.Methods.Single(m => m.Name == "MoveNext");
            var logs = processMove.Body.Instructions.Where(i => i.Operand is MethodReference &&
                ((MethodReference)i.Operand).FullName == "System.Void UnityEngine.Debug::LogError(System.Object)").ToArray();
            if (logs.Length != 2 || !processMove.Body.Instructions.Any(i => (i.Operand as string) == "RealURL = "))
                throw new InvalidDataException("Unexpected loader terminal failure branch");
            var queue = process.Fields.Single(f => f.Name == "queue" && f.FieldType.FullName == "Loader/LoadQueue");
            var queueName = loader.NestedTypes.Single(t => t.Name == "LoadQueue").Fields.Single(f => f.Name == "name_");
            var processIl = processMove.Body.GetILProcessor();
            var q0 = processIl.Create(OpCodes.Ldarg_0);
            var q1 = processIl.Create(OpCodes.Ldfld, queue);
            var q2 = processIl.Create(OpCodes.Ldfld, queueName);
            processIl.InsertAfter(logs[1], q0);
            processIl.InsertAfter(q0, q1);
            processIl.InsertAfter(q1, q2);
            processIl.InsertAfter(q2, processIl.Create(OpCodes.Call, notify));

            // The script-file coroutine otherwise waits forever for a non-null
            // asset. Returning false lets Interpreter report its existing error.
            var library = module.Types.Single(t => t.FullName == "Script.StanderdLibrary");
            var file = library.NestedTypes.Single(t => t.Name.StartsWith("<loadFile>"));
            var fileMove = file.Methods.Single(m => m.Name == "MoveNext");
            var filename = file.Fields.Single(f => f.Name == "filename");
            var pc = file.Fields.Single(f => f.Name == "$PC");
            var fileIl = fileMove.Body.GetILProcessor();
            var originalFirst = fileMove.Body.Instructions[0];
            var check = new Instruction[] {
                fileIl.Create(OpCodes.Ldarg_0), fileIl.Create(OpCodes.Ldfld, filename),
                fileIl.Create(OpCodes.Call, isFailed), fileIl.Create(OpCodes.Brfalse, originalFirst),
                fileIl.Create(OpCodes.Ldarg_0), fileIl.Create(OpCodes.Ldc_I4_M1),
                fileIl.Create(OpCodes.Stfld, pc), fileIl.Create(OpCodes.Ldc_I4_0), fileIl.Create(OpCodes.Ret)
            };
            foreach (var instruction in check) fileIl.InsertBefore(originalFirst, instruction);

            var recover = new MethodDefinition(RecoveryName,
                MethodAttributes.Private | MethodAttributes.HideBySig, module.TypeSystem.Void);
            player.Methods.Add(recover);
            recover.Body.InitLocals = true;
            var pending = new VariableDefinition(callback.FieldType);
            recover.Body.Variables.Add(pending);
            var il = recover.Body.GetILProcessor();
            var done = il.Create(OpCodes.Ret);
            il.Append(il.Create(OpCodes.Ldarg_0));
            il.Append(il.Create(OpCodes.Ldfld, prefix));
            il.Append(il.Create(OpCodes.Ldstr, "scr2_000001_01"));
            il.Append(il.Create(OpCodes.Call, equality));
            il.Append(il.Create(OpCodes.Brfalse, done));
            il.Append(il.Create(OpCodes.Ldarg_0));
            il.Append(il.Create(OpCodes.Ldfld, callback));
            il.Append(il.Create(OpCodes.Stloc, pending));
            il.Append(il.Create(OpCodes.Ldloc, pending));
            il.Append(il.Create(OpCodes.Brfalse, done));
            // Consume before invoking; repeated calls cannot repeat the FSM exit.
            il.Append(il.Create(OpCodes.Ldarg_0));
            il.Append(il.Create(OpCodes.Ldnull));
            il.Append(il.Create(OpCodes.Stfld, callback));
            il.Append(il.Create(OpCodes.Ldarg_0));
            il.Append(il.Create(OpCodes.Call, stop));
            il.Append(il.Create(OpCodes.Ldloc, pending));
            il.Append(il.Create(OpCodes.Callvirt, invoke));
            il.Append(done);

            // Reachable only after Interpreter.IsError and the original error log.
            // Successful scripts, tutorial scripts and event startup remain intact.
            var hook = move.Body.GetILProcessor();
            var loadOwner = hook.Create(OpCodes.Ldarg_0);
            var getOwner = hook.Create(OpCodes.Ldfld, owner);
            hook.InsertAfter(errorLog, loadOwner);
            hook.InsertAfter(loadOwner, getOwner);
            hook.InsertAfter(getOwner, hook.Create(OpCodes.Call, recover));
            move.Body.MaxStackSize = Math.Max(move.Body.MaxStackSize, 2);
            using (var result = new MemoryStream())
            {
                assembly.Write(result);
                using (var outputFile = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
                    result.WriteTo(outputFile);
            }
        }
        return "Added failure-only ordinary startup recovery; progression gates unchanged";
    }
}
