// Copyright 2026 Nikolay Petrov
//
// Licensed under the Apache License, Version 2.0 (the "License").
//
// abicheck Clang facts plugin (ADR-035 D5) — REFERENCE SKELETON.
//
// Optional optimization that emits abicheck's Flow-2 normalized source facts
// (source_facts/*.jsonl, schema = abicheck.buildsource.source_abi.SourceAbiTu)
// straight from the AST Clang already built, removing the second front-end pass
// the `abicheck-cc` wrapper otherwise runs. The supported portable producer
// remains the wrapper + compile_commands.json replay; this plugin is
// compiler-version-sensitive and therefore never required.
//
// This skeleton wires the PluginASTAction so a maintainer can fill in the
// RecursiveASTVisitor body that maps public Decls -> SourceEntity records. It is
// intentionally minimal and not built in abicheck CI.

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendPluginRegistry.h"

#include <fstream>
#include <string>

using namespace clang;

namespace {

// Visits top-level declarations and (TODO) appends one SourceEntity JSON object
// per public declaration to the per-TU facts file. The mapping must mirror
// abicheck/buildsource/source_extractors/base.py::entity_from_* so the emitted
// facts are byte-compatible with the wrapper's output.
class FactsVisitor : public RecursiveASTVisitor<FactsVisitor> {
public:
  explicit FactsVisitor(ASTContext &Ctx, std::ostream &Out) : Ctx(Ctx), Out(Out) {}

  bool VisitNamedDecl(NamedDecl *D) {
    // TODO: classify public surface (visibility/header origin), compute
    // signature_hash / mangled_name, and write one SourceEntity JSON object.
    (void)D;
    (void)Ctx;
    return true;
  }

private:
  ASTContext &Ctx;
  std::ostream &Out;
};

class FactsConsumer : public ASTConsumer {
public:
  explicit FactsConsumer(std::string OutDir) : OutDir(std::move(OutDir)) {}

  void HandleTranslationUnit(ASTContext &Ctx) override {
    // One JSONL line = one SourceAbiTu. Append so parallel TUs each own a file.
    const std::string Path = OutDir + "/source_facts/tu.jsonl";
    std::ofstream Out(Path, std::ios::app);
    if (!Out)
      return;
    FactsVisitor V(Ctx, Out);
    V.TraverseDecl(Ctx.getTranslationUnitDecl());
    // TODO: wrap the visited entities in the SourceAbiTu envelope and emit it.
  }

private:
  std::string OutDir;
};

class FactsAction : public PluginASTAction {
public:
  std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &, llvm::StringRef) override {
    return std::make_unique<FactsConsumer>(OutDir);
  }

  bool ParseArgs(const CompilerInstance &, const std::vector<std::string> &Args) override {
    for (const auto &Arg : Args) {
      const std::string Prefix = "out=";
      if (Arg.rfind(Prefix, 0) == 0)
        OutDir = Arg.substr(Prefix.size());
    }
    return true;
  }

  ActionType getActionType() override { return AddAfterMainAction; }

private:
  std::string OutDir = "abicheck_inputs";
};

} // namespace

static FrontendPluginRegistry::Add<FactsAction>
    X("abicheck-facts", "emit abicheck Flow-2 source facts during compile");
