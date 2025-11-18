Docs Contribution Guide

## Tips for writing and assessing docs:

- **For Overview pages at the start of a section** -> Cover the general concept, add a diagram if necessary, have a basic code snippet, and end with "Learn more" with cards to the details for agents/teams/workflow. This should mostly already be like this, but check.

- **For all pages, make sure:**
    - The title makes sense (that is the one displayed on the page)
    - There is a `sidebarTitle` that makes sense. Often this is `Overview`
    - There is a `keywords` section that makes sense.
    - There is a `description` and that it works with the first lines of the page (and there isn't duplication)
    - The page ends with `Developer Resources` where needed
    - Run `mintlify broken-links` to check whether you have any broken links in your page

- **For examples:**
    - Check the sidebarTitle
    - Rather have less than more examples. We need to cover every case, but it doesn't have to be excessive.
    - Make sure the order of the examples in the side bar makes sense! The most important ones first and the niche ones later
    - Each example should have the code and the usage, with the typical steps to run the file. Don't split this as `Code` and `Usage`, just make it one thing and make it part of the page (i.e. don't have headers unnecessarily)
    - At the top add `mode:wide`
    - Remove any `cookbook/...` from the title of the python snippet and from the code to run that python snippet. It should just be `my_code_file.py` (for example)
    - See `/examples/concepts/agent/input_and_output/input_as_dict` as the golden example



    ------

    When do we want to use mode: wide? I don't get the pattern, feeling it's used in random places
:white_check_mark:
2

5 replies


Dirk
:waning_crescent_moon:  Friday at 5:24 AM
When the table of contents contains nothing or very little (e.g. it is just "Usage" and nothing else) then its better not to show it, and that is what mode: wide does
5:25
So basically, if you want to get rid of the ToC for a better experience
5:25
It is kinda subjective


Manu
  Friday at 5:28 AM
Yeah okay. I think starting at 3 items the toc makes sense, but no point in enforcing strict rules for it :+1:


Dirk
:waning_crescent_moon:  Friday at 5:36 AM
Yeah of course, everyone can use their judgement here




====
We’re not expecting full rewrites of every section or page.
The main goal is to check:
Is it cohesive? Does it make sense to a new user?
Put yourself in the shoes of someone arriving at Agno for the first time — is this sufficient?
When working through your tickets, use the new structure from prototype-restructure.
This will guide what’s needed for each ticket.
For example, if your ticket says Basics > Agents, that means everything under that section should be reviewed as a whole.
Dirk shared some awesome tips that I’ve wrapped up in a Notion doc.
If you discover anything useful or have pro tips to share, please add them there so we can all benefit. :raised_hands:
Any questions — ping me or Dirk.
Let’s aim to have all tickets done by EOD tomorrow, so we can spend Monday refining, reviewing, and merging updates.
There’s still a lot to do to get ready for Tuesday’s launch. :pray:


----
Also important on the docs: Rename any files you touch to have - in the file name instead of _ -> The file names directly translate to URLs and have to be hyphens. E.g. not my_cool_example.mdx but my-cool-example.mdx. And remember to then update the docs.json and any other references to that file.
Check whether reference got broken with mintlify broken-links



-----
Team, reminder, that a ticket like this https://linear.app/agno/issue/CON-54/update-cleanup-basics-agents
Is not just about the Basics-Agents-Overview page, but everything in that section. Overview + Building, Running, Debugging and Usage/Examples.
A simple read over, minor corrections or coherency fix if needed.